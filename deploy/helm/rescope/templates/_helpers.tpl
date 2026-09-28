{{- define "rescope.labels" -}}
app.kubernetes.io/part-of: rescope
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end }}

{{- define "rescope.selector" -}}
app.kubernetes.io/part-of: rescope
app.kubernetes.io/instance: {{ .root.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end }}

{{- define "rescope.image" -}}
{{- $img := index .root.Values.images .name -}}
{{- required (printf "images.%s.tag is required" .name) $img.tag | printf "%s:%s" $img.repository -}}
{{- end }}

{{/* Env shared by api, worker and scraper; mirrors infra/docker-compose.prod.yml. */}}
{{- define "rescope.appEnv" -}}
- name: POSTGRES_PASSWORD
  valueFrom: { secretKeyRef: { name: {{ .Values.secret.name }}, key: POSTGRES_PASSWORD } }
- name: RESCOPE_APP_ROLE_PASSWORD
  valueFrom: { secretKeyRef: { name: {{ .Values.secret.name }}, key: RESCOPE_APP_ROLE_PASSWORD } }
- name: MASTER_KEY
  valueFrom: { secretKeyRef: { name: {{ .Values.secret.name }}, key: MASTER_KEY } }
- name: ANTHROPIC_API_KEY
  valueFrom: { secretKeyRef: { name: {{ .Values.secret.name }}, key: ANTHROPIC_API_KEY, optional: true } }
- name: BROWSER_USE_API_KEY
  valueFrom: { secretKeyRef: { name: {{ .Values.secret.name }}, key: BROWSER_USE_API_KEY, optional: true } }
- name: DATABASE_URL
  value: postgresql+asyncpg://rescope:$(POSTGRES_PASSWORD)@{{ .Release.Name }}-postgres:5432/rescope
- name: APP_DATABASE_URL
  value: postgresql+asyncpg://rescope_app:$(RESCOPE_APP_ROLE_PASSWORD)@{{ .Release.Name }}-postgres:5432/rescope
- name: REDIS_URL
  value: redis://{{ .Release.Name }}-redis:6379/0
- name: EMBEDDINGS_URL
  value: http://{{ .Release.Name }}-embeddings:80
- name: ENVIRONMENT
  value: production
- name: ROOT_DOMAIN
  value: {{ .Values.domain | quote }}
- name: DEBUG
  value: "false"
{{- end }}

{{/* Takes (list uid gid); the numeric ids must match the image's own USER. */}}
{{- define "rescope.podSecurity" -}}
securityContext:
  runAsNonRoot: true
  runAsUser: {{ index . 0 }}
  runAsGroup: {{ index . 1 }}
  fsGroup: {{ index . 1 }}
  seccompProfile: { type: RuntimeDefault }
{{- end }}

{{- define "rescope.containerSecurity" -}}
securityContext:
  allowPrivilegeEscalation: false
  readOnlyRootFilesystem: true
  capabilities: { drop: ["ALL"] }
{{- end }}
