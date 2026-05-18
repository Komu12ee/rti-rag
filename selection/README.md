# Selection + Login System

This folder contains the complete authentication and pipeline selection system for CHiPS-RAG.

## Structure

```
selection/
├── routes/
│   ├── otp-auth.js       # OTP authentication routes (signup, login, etc.)
│   └── select.js         # Pipeline selection page and launch API
└── public/
    ├── otp-auth.js       # OTP authentication UI (screens and logic)
    └── otp-auth.css      # OTP authentication styles
```

## Routes

### OTP Authentication Routes (`/otp-auth`)
- `POST /otp-auth/send-otp` - Request OTP for email
- `POST /otp-auth/verify-otp` - Verify OTP code
- `POST /otp-auth/register` - Complete registration with password
- `POST /otp-auth/login` - Login with email + password
- `POST /otp-auth/logout` - Client-side logout

### Pipeline Selection Routes (`/select`)
- `GET /select` - Pipeline selection page (protected)
- `POST /select/launch` - Launch a pipeline

## User Flow

1. User visits `/` and sees OTP auth gate
2. User signs up or logs in (both handled by OTP auth system)
3. After successful login, user is redirected to `/select`
4. User sees two pipeline cards (CHiPS RAG, Finance/GAD RAG)
5. User clicks "Launch Pipeline" to select one
6. Pipeline is spawned in background
7. User is redirected to `/index.html` (main RAG UI)
8. All `/api/*` requests proxy to the selected pipeline's Flask backend

## Important Notes

### Import Paths
Files in `/selection/routes/` import from the main nodejs folder using relative paths:
- `../../CHiPS/05_webui/nodejs/config` - For configuration
- `../../CHiPS/05_webui/nodejs/utils/*` - For utilities (db, email, pipelines, etc.)

This is intentional to keep the selection system modular while maintaining access to shared infrastructure.

### Frontend Assets
- OTP auth CSS is served as `/otp-auth.css` - linked in the OTP auth gate HTML
- OTP auth JS is served as `/otp-auth.js` - loaded before the main app

### Session Management
- Auth state stored in a session cookie `chips_rag_session`
- Active pipeline stored in HTTP-only cookie `active_pipeline`
- Cookie is used by proxy middleware to route requests to correct Flask backend

## File Locations in Main Server

The files in this folder are imported in `/nodejs/server.js`:
```javascript
const otpAuthRouter = require('../selection/routes/otp-auth');
const selectRouter = require('../selection/routes/select');

app.use('/otp-auth', express.json(), otpAuthRouter);
app.use('/select', express.json(), selectRouter);
```

## Related Files

- Main server: `/nodejs/server.js`
- Pipeline management: `/nodejs/utils/pipelines.js`
- Configuration: `/nodejs/config.js`
- Frontend (RAG UI): `/nodejs/public/index.html` and `/nodejs/public/app.js`
