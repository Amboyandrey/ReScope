output "node_public_ip" {
  description = "Point each environment's domain and its wildcard A records here."
  value       = aws_eip.node.public_ip
}

output "instance_id" {
  description = "For `aws ssm start-session --target <id>`."
  value       = aws_instance.node.id
}

output "backups_bucket" {
  description = "Set as backup.bucket in each environment's values."
  value       = aws_s3_bucket.backups.bucket
}
