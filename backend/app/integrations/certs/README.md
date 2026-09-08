# AWS RDS ap-east-1 CA bundle

Public CA certificates, downloaded on 2026-09-08 from:
https://truststore.pki.rds.amazonaws.com/ap-east-1/ap-east-1-bundle.pem

SHA-256: `92b5a6d3e9b159ca3e1daa954b3247af19149f037cd44ab7180e8bff6c862513`

Production uses this bundle through `DA_REPORT_MYSQL_SSL_CA`; certificate and hostname verification
remain enabled. It contains no application credentials or private keys. Review AWS RDS CA rotation
notices, update from the official trust store, validate the certificates and record the new hash
before rebuilding the image. SQLite/UAT does not use this bundle unless MySQL is explicitly configured.
