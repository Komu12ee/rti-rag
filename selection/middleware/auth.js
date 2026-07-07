'use strict';

/**
 * Authentication middleware
 * Checks for active session cookie (chips_rag_session)
 * If not authenticated, redirects to home or returns 401
 */
module.exports = (req, res, next) => {
    // Check if user has an active session
    if (req.cookies?.chips_rag_session) {
        // User is authenticated, continue
        return next();
    }

    // User is not authenticated
    // If they're requesting JSON (API), return 401
    if (req.accepts('json')) {
        return res.status(401).json({ success: false, error: 'Unauthorized' });
    }

    // Otherwise redirect to home
    res.redirect('/');
};
