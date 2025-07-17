{{- define "postgres.labels" -}}
app.kubernetes.io/name: chutes-postgres
{{- end }}

{{- define "redis.labels" -}}
app.kubernetes.io/name: chutes-redis
{{- end }}

{{- define "registry.labels" -}}
app.kubernetes.io/name: chutes-registry
{{- end }}

{{- define "chutes.labels" -}}
chutes/chute: "true"
{{- end }}

{{- define "bootstrap.labels" -}}
node-bootstrap: "true"
{{- end }}

{{- define "agent.labels" -}}
app.kubernetes.io/name: agent
postgres-access: "true"
redis-access: "true"
{{- end }}

{{- define "gepetto.labels" -}}
app.kubernetes.io/name: gepetto
postgres-access: "true"
redis-access: "true"
{{- end }}
