# Certificados (não vão para o git)

Certificado de **origem** da Cloudflare, lido pelo nginx:

| Arquivo       | O que é                                   |
| ------------- | ----------------------------------------- |
| `origin.pem`  | certificado (Origin Certificate)          |
| `origin.key`  | chave privada                             |

Na Cloudflare: **SSL/TLS → Origin Server → Create certificate** (RSA, o domínio e `*.domínio`, 15 anos).
Cole o certificado em `origin.pem` e a chave em `origin.key`. Depois, em **SSL/TLS → Overview**, use
**Full (strict)** e deixe o DNS do domínio com proxy (nuvem laranja): o certificado de origem só é aceito
pela Cloudflare, não pelo navegador direto.

**Authenticated Origin Pulls** (ligado por padrão, `NGINX_CF_ORIGIN_PULL=on`): só a Cloudflare consegue falar com
o servidor. Ligue também na Cloudflare em **SSL/TLS → Origin Server → Authenticated Origin Pulls**. O CA público
dela já vem em `nginx/cloudflare/origin-pull-ca.pem`. Sem Cloudflare na frente, use `NGINX_CF_ORIGIN_PULL=off`.

```bash
chmod 600 origin.key
```
