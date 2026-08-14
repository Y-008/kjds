# Secrets Boundary

This directory is intentionally empty in Git.

Production and local rehearsal deployments must inject file-backed secrets here
or point the `*_FILE` environment variables in `customer-scope.example.env` to
external secret-manager exports.

Required secret files:

- `postgres-password.txt`
- `database-url.txt`
- `api-key.txt`
- `api-keys.json`
- `web-user-actors.json`
- `web-user-actors.json`
- `channel-lease-signing-key.txt`
- `next-public-supabase-url.txt`
- `next-public-supabase-publishable-key.txt`
- `tls.crt`
- `tls.key`

`api-keys.json` must bind every credential to the exact customer tenant and
store list. `web-user-actors.json` must bind distinct Supabase users to the
operator and approver actors declared in that credential map.
