variable "slack_webhook_url" {
  description = "Slack Incoming Webhook URL for cost notifications"
  type        = string
  sensitive   = true  # 機密情報として扱う
}
