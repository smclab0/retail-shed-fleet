{{- define "store-pos.collect" -}}
{{- if eq (toString .Values.collect.enabled) "true" }}true{{ end -}}
{{- end -}}

{{/* deployment name mode */}}
{{- define "store-pos.deployment" -}}
{{- $ := index . 0 }}{{ $mode := index . 1 -}}
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ $mode }}
  labels: {app: store-pos, mode: {{ $mode }}}
spec:
  replicas: 1
  strategy: {type: Recreate}   # SQLite on a ReadWriteOnce volume
  selector:
    matchLabels: {app: store-pos, mode: {{ $mode }}}
  template:
    metadata:
      labels: {app: store-pos, mode: {{ $mode }}}
      annotations:
        checksum/prices: {{ toJson $.Values.prices | sha256sum }}
    spec:
      securityContext: {runAsUser: 1000, runAsGroup: 1000, fsGroup: 1000, runAsNonRoot: true}
      containers:
        - name: app
          image: "{{ $.Values.image.repository }}:{{ $.Values.image.tag }}"
          ports: [{name: http, containerPort: 8080}]
          env:
            - {name: MODE, value: {{ $mode | quote }}}
            - {name: STORE_ID, value: {{ $.Values.store.id | quote }}}
            - {name: STORE_REGION, value: {{ $.Values.store.region | quote }}}
            - {name: STORE_TIER, value: {{ $.Values.store.tier | quote }}}
            - {name: HQ_URL, value: {{ $.Values.hqUrl | quote }}}
            - {name: CURRENCY, value: {{ $.Values.currency | quote }}}
            - {name: BANNER, value: {{ $.Values.banner | quote }}}
          readinessProbe: {httpGet: {path: /healthz, port: http}, periodSeconds: 5}
          livenessProbe: {httpGet: {path: /healthz, port: http}, periodSeconds: 20}
          resources:
            requests: {cpu: 20m, memory: 32Mi}
            limits: {memory: 128Mi}
          securityContext: {allowPrivilegeEscalation: false, capabilities: {drop: [ALL]}}
          volumeMounts:
            - {name: data, mountPath: /data}
            - {name: config, mountPath: /config}
      volumes:
        - name: data
          persistentVolumeClaim: {claimName: {{ $mode }}-data}
        - name: config
          configMap: {name: prices}
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: {{ $mode }}-data
spec:
  accessModes: [ReadWriteOnce]
  resources: {requests: {storage: 256Mi}}
---
apiVersion: v1
kind: Service
metadata:
  name: {{ $mode }}
spec:
  selector: {app: store-pos, mode: {{ $mode }}}
  ports: [{name: http, port: 80, targetPort: http}]
{{- end -}}
