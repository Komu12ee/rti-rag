// Auto-initialize OTP Auth Gate
console.log('[init] OTP auth initialization script loaded');

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
        console.log('[init] DOM loaded, initializing OTP auth');
        if (typeof initializeOTPAuthGate === 'function') {
            initializeOTPAuthGate();
        } else {
            console.warn('[init] initializeOTPAuthGate not found in window');
        }
    });
} else {
    console.log('[init] Document already loaded, initializing immediately');
    if (typeof initializeOTPAuthGate === 'function') {
        initializeOTPAuthGate();
    } else {
        console.warn('[init] initializeOTPAuthGate not found');
    }
}
