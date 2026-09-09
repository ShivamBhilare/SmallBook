/**
 * SmallBook - Authentication Forms Components
 * Provides Alpine.js controllers for Sign In, Sign Up, Password Reset,
 * Password Update, and Email Verification.
 */

function signInForm() {
    return {
        email: '',
        password: '',
        showPassword: false,
        loading: false,
        errorMsg: '',
        successMsg: '',
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

function signUpForm() {
    return {
        fullname: '',
        email: '',
        password: '',
        showPassword: false,
        loading: false,
        errorMsg: '',
        successMsg: '',
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

function forgotPasswordForm() {
    return {
        email: '',
        loading: false,
        errorMsg: '',
        successMsg: '',
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

function verifyEmailState(serverEmail = '') {
    return {
        email: new URLSearchParams(window.location.search).get('email') || serverEmail || '',
        loading: false,
        successMsg: '',
        errorMsg: '',
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
