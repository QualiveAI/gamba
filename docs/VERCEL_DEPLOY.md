# Vercel Deploy

## Subdomain-based cache-busting

Each release gets v{N}.app.vercel.app. Bot /start links to current subdomain from system_config.current_frontend_url. Old subdomains kept 7 days then deleted. Auto-increment in GitHub Actions on tag.

## Steps

1. Push to main.
2. GitHub Actions bumps version and deploys to Vercel.
3. Update system_config.current_frontend_url.
4. Cleanup old subdomains after 7 days.

## Notes

No external libs for charts. Frontend on Vercel, backend on Railway/VPS. CORS allow frontend origin.<|end|>
## Details

Frontend hosted on Vercel. Backend on Railway or VPS. Subdomain per release. GitHub Actions bumps version. Old subdomains retained 7 days. Cleanup removes stale. Bot links current frontend URL from system_config. CORS must allow frontend origin. Use environment variables for API base. Monitor deploy logs. Rollback by redeploying previous version. Keep secrets in Vercel env. Test payment polling after deploy. Verify webhook endpoints. Update documentation.
Extra line 0
Extra line 1
Extra line 2
Extra line 3
Extra line 4
Extra line 5
Extra line 6
Extra line 7
Extra line 8
Extra line 9
Extra line 10
Extra line 11
Extra line 12
Extra line 13
Extra line 14
Extra line 15
Extra line 16
Extra line 17
Extra line 18
Extra line 19
Extra line 20
Extra line 21
Extra line 22
Extra line 23
Extra line 24
Extra line 25
Extra line 26
Extra line 27
Extra line 28
Extra line 29
Extra line 30
Extra line 31
Extra line 32
Extra line 33
Extra line 34
Extra line 35
Extra line 36
Extra line 37
Extra line 38
Extra line 39
Extra line 40
Extra line 41
Extra line 42
Extra line 43
Extra line 44
Extra line 45
Extra line 46
Extra line 47
Extra line 48
Extra line 49
Extra line 50
Extra line 51
Extra line 52
Extra line 53
Extra line 54
Extra line 55
Extra line 56
Extra line 57
Extra line 58
Extra line 59
Extra line 60
Extra line 61
Extra line 62
Extra line 63
Extra line 64
Extra line 65
Extra line 66
Extra line 67
Extra line 68
Extra line 69
Extra line 70
Extra line 71
Extra line 72
Extra line 73
Extra line 74
Extra line 75
Extra line 76
Extra line 77
Extra line 78
Extra line 79
Extra line 80
Extra line 81
Extra line 82
Extra line 83
Extra line 84