variable "region" {
  description = "AWS region for every resource."
  type        = string
  default     = "ap-southeast-1"
}

variable "instance_type" {
  description = "Single k3s node; staging and prod each run Postgres, TEI and Chromium, so 16 GB is the floor."
  type        = string
  default     = "t3.xlarge"
}

variable "use_spot" {
  description = "Persistent spot request that stops (not terminates) on interruption, keeping the root volume."
  type        = bool
  default     = true
}

variable "root_volume_gb" {
  description = "Root EBS size; holds k3s, images and every local-path PersistentVolume."
  type        = number
  default     = 60
}

variable "k3s_version" {
  description = "Pinned k3s release so a rebuilt node never silently upgrades Kubernetes."
  type        = string
  default     = "v1.36.4+k3s1"
}

variable "admin_cidrs" {
  description = "CIDRs allowed to reach the Kubernetes API on 6443; there is no SSH, shell access is via SSM."
  type        = list(string)

  validation {
    condition     = length(var.admin_cidrs) > 0 && !contains(var.admin_cidrs, "0.0.0.0/0")
    error_message = "admin_cidrs must list specific addresses, never 0.0.0.0/0."
  }
}

variable "backup_retention_days" {
  description = "Days a Postgres dump is kept in S3 before lifecycle expiry."
  type        = number
  default     = 30
}

variable "monthly_budget_usd" {
  description = "AWS Budgets alert threshold for this project's monthly spend."
  type        = number
  default     = 60
}

variable "budget_alert_email" {
  description = "Where budget alerts are sent."
  type        = string
}
