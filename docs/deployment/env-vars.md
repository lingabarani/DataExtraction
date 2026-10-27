# Environment Variables Reference

| Variable | Required | Default | Description |
|:---|:---:|:---|:---|
| `POSTGRES_HOST` | Yes | `localhost` | PostgreSQL database hostname |
| `POSTGRES_PORT` | Yes | `5432` | PostgreSQL database port |
| `POSTGRES_DB` | Yes | `dataextraction` | Database name |
| `POSTGRES_USER` | Yes | `dex_user` | Database user |
| `POSTGRES_PASSWORD` | Yes | - | Database password |
| `POSTGRES_POOL_SIZE` | No | `20` | Threaded connection pool capacity |
| `TEMPORAL_HOST` | Yes | `localhost:7233` | Temporal server endpoint |
| `TEMPORAL_NAMESPACE` | No | `default` | Temporal execution namespace |
| `JWT_SECRET_KEY` | Yes | - | Secret key for JWT session tokens |
| `JWT_ALGORITHM` | No | `HS256` | JWT signing algorithm |
| `API_ADMIN_EMAIL` | Yes | `admin@dataextraction.io` | Default administrative account email |
| `API_ADMIN_PASSWORD` | Yes | - | Administrative account password |
| `AGENT_DLQ_AUTO_REPLAY_THRESHOLD` | No | `100` | Auto-replay ceiling for DLQ agent |
| `AGENT_DB_POOL_THROTTLE_THRESHOLD` | No | `0.85` | DB pool utilization threshold to trigger worker throttle |
| `GOOGLE_MAPS_API_KEY` | No | - | Optional Google Maps API key for 3D marker enrichment |
| `PROMETHEUS_PORT` | No | `9090` | Metrics telemetry exporter port |

