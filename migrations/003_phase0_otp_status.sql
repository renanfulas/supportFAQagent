-- Migration 003 - Align OTP terminal states with the Python service.

ALTER TABLE otp_challenges
  DROP CONSTRAINT IF EXISTS otp_challenges_status_check;

ALTER TABLE otp_challenges
  ADD CONSTRAINT otp_challenges_status_check
  CHECK (status IN ('pending', 'consumed', 'expired', 'exhausted', 'delivery_failed'));
