# RB-007: RabbitMQ Queue Backlog

| Field         | Value                                                    |
|---------------|----------------------------------------------------------|
| **Service**   | notification-service                                     |
| **Severity**  | P2 - High                                                |
| **Last Updated** | 2026-02-10                                            |
| **Author**    | Platform Engineering / ShopFast SRE                      |
| **Alert**     | `RabbitMQQueueBacklog`                                   |

## Symptoms

- **Alert fires:** `RabbitMQQueueBacklog` with labels `queue=shopfast.notifications`, `namespace=shopfast-prod` when queue depth exceeds 10,000 messages for more than 5 minutes
- **Grafana dashboard:** "ShopFast / RabbitMQ" shows `shopfast.notifications` queue depth growing linearly, consumer count low or zero
- **Metrics:**
  - `rabbitmq_queue_messages{queue="shopfast.notifications"} > 10000`
  - `rabbitmq_queue_consumers{queue="shopfast.notifications"} < expected` (expected: 3 per pod, 4 pods = 12)
  - `rabbitmq_queue_messages_unacknowledged{queue="shopfast.notifications"}` growing
  - `rabbitmq_queue_messages_published_total` rate significantly higher than `rabbitmq_queue_messages_delivered_total`
- **User impact:** Order confirmation emails delayed. Shipping notification SMS not sent. Customers calling support about missing confirmations.
- **Logs:** notification-service logs may show `com.rabbitmq.client.ShutdownSignalException` or `Channel shutdown: connection error` or consumer threads blocked on downstream calls (SMTP, SMS gateway)

## Investigation Steps

### 1. Check queue status in RabbitMQ

```bash
kubectl exec -n shopfast-prod rabbitmq-0 -- rabbitmqctl list_queues name messages consumers message_bytes | grep shopfast
kubectl exec -n shopfast-prod rabbitmq-0 -- rabbitmqctl list_queues name messages_ready messages_unacknowledged | grep shopfast
```

### 2. Check notification-service consumer pods

```bash
kubectl get pods -n shopfast-prod -l app=notification-service
kubectl logs -n shopfast-prod -l app=notification-service --tail=100 | grep -i "error\|exception\|timeout\|rejected\|nack"
```

### 3. Check consumer connection status

```bash
kubectl exec -n shopfast-prod rabbitmq-0 -- rabbitmqctl list_connections user client_properties state | grep notification
kubectl exec -n shopfast-prod rabbitmq-0 -- rabbitmqctl list_consumers queue_name channel_pid consumer_tag ack_required | grep shopfast.notifications
```

### 4. Check the dead letter queue

```bash
kubectl exec -n shopfast-prod rabbitmq-0 -- rabbitmqctl list_queues name messages | grep "dead-letter\|dlq\|DLX"
# High DLQ count means messages are failing and being rejected
```

### 5. Check downstream dependencies (SMTP, SMS gateway)

```bash
# Check if the SMTP relay is reachable
kubectl exec -n shopfast-prod deploy/notification-service -- curl -sv --max-time 5 telnet://smtp-relay.shopfast-prod.svc.cluster.local:587 2>&1 | head -10

# Check SMS gateway health
kubectl exec -n shopfast-prod deploy/notification-service -- curl -s --max-time 5 https://api.twilio.com/2010-04-01/.json | jq .status
```

### 6. Check RabbitMQ node health

```bash
kubectl exec -n shopfast-prod rabbitmq-0 -- rabbitmqctl node_health_check
kubectl exec -n shopfast-prod rabbitmq-0 -- rabbitmqctl status | grep -A5 "memory\|disk_free\|file_descriptors"
kubectl top pods -n shopfast-prod -l app=rabbitmq
```

### 7. Check publish rate vs consume rate

```bash
# RabbitMQ Management API (if enabled)
kubectl exec -n shopfast-prod rabbitmq-0 -- curl -s -u guest:guest http://localhost:15672/api/queues/%2F/shopfast.notifications | jq '{messages, consumers, message_stats: {publish_details: .message_stats.publish_details.rate, deliver_details: .message_stats.deliver_get_details.rate}}'
```

## Remediation

### Immediate (restore throughput)

1. **Scale up notification-service consumers:**

```bash
kubectl scale deployment/notification-service -n shopfast-prod --replicas=8
kubectl rollout status deployment/notification-service -n shopfast-prod --timeout=120s
```

2. **If consumers are stuck, rolling restart:**

```bash
kubectl rollout restart deployment/notification-service -n shopfast-prod
```

3. **If the dead letter queue is growing, purge it after investigation (messages are already failed):**

```bash
kubectl exec -n shopfast-prod rabbitmq-0 -- rabbitmqctl purge_queue shopfast.notifications.dlq
```

4. **If SMTP/SMS gateway is down and the backlog is growing, temporarily pause consumers to prevent DLQ overflow and wait for provider recovery:**

```bash
kubectl scale deployment/notification-service -n shopfast-prod --replicas=0
# Re-scale once the downstream provider is back
```

5. **If RabbitMQ is running out of disk or memory, apply flow control thresholds:**

```bash
kubectl exec -n shopfast-prod rabbitmq-0 -- rabbitmqctl set_vm_memory_high_watermark 0.6
```

### Root Cause

- **Consumer crash or disconnect:** Check if notification-service pods restarted recently. A restart causes consumers to re-register, potentially missing messages during the gap.
- **Downstream timeout:** If SMTP relay or SMS gateway is slow, each consumer thread blocks, reducing overall throughput. Check `notification_send_duration_seconds` metric.
- **Publish spike:** A large batch of orders (e.g., flash sale) can produce thousands of notification messages. Check `order_completed_total` rate for unusual spikes.
- **Prefetch too low:** If `spring.rabbitmq.listener.simple.prefetch` is set to 1, throughput is limited. Recommended value: 10-25 for notification workloads.
- **Unacknowledged messages:** If consumers are not acking messages, they stay in unacked state and RabbitMQ cannot deliver new ones. Check for blocking I/O in the consumer handler.

## Escalation

| Condition                                               | Action                                        |
|---------------------------------------------------------|-----------------------------------------------|
| Queue depth > 100,000 messages                          | P1 escalation, page notification-service team |
| RabbitMQ node memory > 80% or disk alarm triggered      | Page Infrastructure / Messaging team          |
| Downstream provider (SMTP/SMS) outage confirmed         | Notify Customer Support, create incident      |
| Backlog not draining after scaling to 8+ replicas       | Engage Platform Engineering for triage        |
| DLQ growing faster than 1000 messages/minute            | Investigate message format or schema issue    |
