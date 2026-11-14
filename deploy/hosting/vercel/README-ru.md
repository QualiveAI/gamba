# Vercel configuration fragment for the prepared API wrapper.
# The repository root vercel.json already owns static rewrites.
# Merge the crons block manually after copying api/ to the repository root:
#
# "crons": [
#   { "path": "/api/cron/auto-pause", "schedule": "*/10 * * * *" }
# ]
#
# Set CRON_SECRET in Vercel Environment Variables. The cron handler returns 404
# without Authorization: Bearer <CRON_SECRET>. Do not place the secret in git.
