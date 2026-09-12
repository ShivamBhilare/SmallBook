/**
 * @fileoverview Authentication Forms Components.
 * Provides reactive Alpine.js controllers for Sign In, Sign Up, Password Reset,
 * Password Update, and Email Verification workflows with inline validation and state.
 */

/* ==========================================================================
   SIGN IN FORM CONTROLLER
   ========================================================================== */

/**
 * Alpine component for user login credential submission.
 *
 * @returns {Object} Alpine data object managing sign-in state.
 */
function signInForm() {
    return {
        email: '',
        password: '',
        showPassword: false,
        loading: false,
        errorMsg: '',
        successMsg: '',

        /**
         * Submits sign-in credentials to backend and handles redirect on success.
         * @returns {Promise<void>}
         */
        async submitForm() {
            this.errorMsg = '';
            this.successMsg = '';
            this.loading = true;
            try {
                const res = await fetch('/auth/api/sign-in', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email: this.email, password: this.password })
                });
                const data = await res.json();
                if (!res.ok) {
                    throw new Error(data.detail || 'Sign in failed');
                }
                this.successMsg = 'Signed in successfully! Redirecting...';
                setTimeout(() => {
                    window.location.href = data.redirect_url || '/notebooks/dashboard';
                }, 500);
            } catch (err) {
                this.errorMsg = err.message;
            } finally {
                this.loading = false;
            }
        }
    };
}

/* ==========================================================================
   SIGN UP FORM CONTROLLER
   ========================================================================== */

/**
 * Alpine component for new user account registration.
 *
 * @returns {Object} Alpine data object managing sign-up state.
 */
function signUpForm() {
    return {
        fullname: '',
        email: '',
        password: '',
        showPassword: false,
        loading: false,
        errorMsg: '',
        successMsg: '',

        /**
         * Submits registration data to backend and routes to dashboard or verification.
         * @returns {Promise<void>}
         */
        async submitForm() {
            this.errorMsg = '';
            this.successMsg = '';
            this.loading = true;
            try {
                const res = await fetch('/auth/api/sign-up', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        email: this.email,
                        password: this.password,
                        fullname: this.fullname
                    })
                });
                const data = await res.json();
                if (!res.ok) {
                    throw new Error(data.detail || 'Registration failed');
                }
                if (data.session) {
                    this.successMsg = data.message || 'Account created! Redirecting...';
                    setTimeout(() => {
                        window.location.href = data.redirect_url || '/notebooks/dashboard';
                    }, 500);
                } else {
                    this.successMsg = data.message || 'Account created! Please check your email to confirm.';
                    setTimeout(() => {
                        window.location.href = `/auth/verify-email?email=${encodeURIComponent(this.email.trim())}`;
                    }, 1200);
                }
            } catch (err) {
                this.errorMsg = err.message;
            } finally {
                this.loading = false;
            }
        }
    };
}

/* ==========================================================================
   FORGOT PASSWORD FORM CONTROLLER
   ========================================================================== */

/**
 * Alpine component for requesting a password recovery email.
 *
 * @returns {Object} Alpine data object managing forgot password state.
 */
function forgotPasswordForm() {
    return {
        email: '',
        loading: false,
        errorMsg: '',
        successMsg: '',

        /**
         * Submits recovery email address to trigger reset email delivery.
         * @returns {Promise<void>}
         */
        async submitForm() {
            this.errorMsg = '';
            this.successMsg = '';
            this.loading = true;
            try {
                const res = await fetch('/auth/api/forgot-password', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email: this.email })
                });
                const data = await res.json();
                if (!res.ok) {
                    throw new Error(data.detail || 'Password reset request failed');
                }
                this.successMsg = data.message || 'If an account exists with that email, a password reset link has been sent.';
            } catch (err) {
                this.errorMsg = err.message;
            } finally {
                this.loading = false;
            }
        }
    };
}

/* ==========================================================================
   UPDATE PASSWORD FORM CONTROLLER
   ========================================================================== */

/**
 * Alpine component for updating password using an active recovery token.
 *
 * @param {string} [initialError=''] - Server-rendered initial error message.
 * @returns {Object} Alpine data object managing password reset submission.
 */
function updatePasswordForm(initialError = '') {
    return {
        password: '',
        confirmPassword: '',
        accessToken: '',
        refreshToken: '',
        showPassword1: false,
        showPassword2: false,
        loading: false,
        errorMsg: initialError || '',
        successMsg: '',

        /**
         * Parses access/recovery tokens from URL hash or search params.
         */
        init() {
            // Parse tokens from URL hash (Supabase default) or search parameters
            const urlParams = new URLSearchParams(window.location.search);
            const hashParams = new URLSearchParams(window.location.hash.startsWith('#') ? window.location.hash.substring(1) : window.location.hash);

            this.accessToken = hashParams.get('access_token') || urlParams.get('access_token') || urlParams.get('token') || '';
            this.refreshToken = hashParams.get('refresh_token') || urlParams.get('refresh_token') || '';

            if (!this.accessToken && !this.errorMsg) {
                this.errorMsg = 'Recovery token missing or expired. Please request a new password reset link.';
            }
        },

        /**
         * Validates password criteria and submits new password to backend.
         * @returns {Promise<void>}
         */
        async submitForm() {
            this.errorMsg = '';
            this.successMsg = '';

            if (this.password !== this.confirmPassword) {
                this.errorMsg = 'Passwords do not match.';
                return;
            }
            if (this.password.length < 6) {
                this.errorMsg = 'Password must be at least 6 characters.';
                return;
            }
            if (!this.accessToken) {
                this.errorMsg = 'Recovery token missing. Please request a new password reset link.';
                return;
            }

            this.loading = true;
            try {
                const res = await fetch('/auth/api/update-password', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        access_token: this.accessToken,
                        refresh_token: this.refreshToken,
                        password: this.password
                    })
                });
                const data = await res.json();
                if (!res.ok) {
                    throw new Error(data.detail || 'Password update failed');
                }
                this.successMsg = data.message || 'Password updated successfully! Redirecting to sign in...';
                setTimeout(() => {
                    window.location.href = data.redirect_url || '/auth/sign-in';
                }, 1500);
            } catch (err) {
                this.errorMsg = err.message;
            } finally {
                this.loading = false;
            }
        }
    };
}

/* ==========================================================================
   EMAIL VERIFICATION CONTROLLER
   ========================================================================== */

/**
 * Alpine component for the email confirmation screen with resend link capability.
 *
 * @param {string} [serverEmail=''] - Default recipient email passed from server context.
 * @returns {Object} Alpine data object managing verification state.
 */
function verifyEmailState(serverEmail = '') {
    return {
        email: new URLSearchParams(window.location.search).get('email') || serverEmail || '',
        loading: false,
        successMsg: '',
        errorMsg: '',

        /**
         * Re-requests delivery of an email verification confirmation link.
         * @returns {Promise<void>}
         */
        async resendVerification() {
            if (!this.email || !this.email.includes('@')) {
                this.errorMsg = 'Please provide a valid email address.';
                this.successMsg = '';
                return;
            }
            this.loading = true;
            this.errorMsg = '';
            this.successMsg = '';
            try {
                const res = await fetch('/auth/api/resend-verification', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email: this.email.trim() })
                });
                const data = await res.json();
                if (!res.ok) {
                    throw new Error(data.detail || 'Failed to resend verification link.');
                }
                this.successMsg = data.message || 'Verification link has been resent!';
            } catch (err) {
                this.errorMsg = err.message;
            } finally {
                this.loading = false;
            }
        }
    };
}
