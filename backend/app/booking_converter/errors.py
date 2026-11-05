"""Errors the converter raises. Each carries a stable ``code`` and a user-safe ``message`` (never raw upstream text)."""

from __future__ import annotations


class ConverterError(Exception):
    status_code = 400
    code = "converter_error"

    def __init__(self, message: str | None = None):
        self.message = message or self.default_message
        super().__init__(self.message)

    default_message = "The conversion could not be completed."


class FeatureDisabled(ConverterError):
    status_code, code = 503, "feature_disabled"
    default_message = "The booking code converter is switched off right now."


class InvalidBookingCode(ConverterError):
    status_code, code = 422, "invalid_code"
    default_message = "That doesn't look like a valid booking code. Check it and try again."


class UnsupportedBookmaker(ConverterError):
    status_code, code = 422, "unsupported_bookmaker"
    default_message = "That bookmaker is not supported."


class SameBookmaker(ConverterError):
    status_code, code = 422, "same_bookmaker"
    default_message = "Choose two different bookmakers."


class IntegrationUnavailable(ConverterError):
    """The bookmaker is known but no legitimate integration is connected for the requested capability."""

    status_code, code = 503, "integration_unavailable"
    default_message = "This bookmaker isn't connected yet."


class BookingCodeNotFound(ConverterError):
    status_code, code = 404, "code_not_found"
    default_message = "The bookmaker could not find that booking code. It may be wrong or expired."


class UpstreamError(ConverterError):
    status_code, code = 502, "upstream_error"
    default_message = "The bookmaker did not respond in time. Please try again in a moment."


class GenerationFailed(ConverterError):
    status_code, code = 502, "generation_failed"
    default_message = "The destination bookmaker did not return a booking code."


class ConversionNotFound(ConverterError):
    status_code, code = 404, "conversion_not_found"
    default_message = "That conversion has expired. Start again."


class ConversionBusy(ConverterError):
    status_code, code = 409, "conversion_in_progress"
    default_message = "This conversion is already running. Please wait a moment."


class NeedsDecision(ConverterError):
    status_code, code = 409, "needs_decision"
    default_message = "Some selections could not be matched. Confirm that you want to continue with the matched ones."


class NothingToConvert(ConverterError):
    status_code, code = 422, "nothing_to_convert"
    default_message = "None of the selections could be matched, so there is nothing to convert."


class WrongState(ConverterError):
    status_code, code = 409, "wrong_state"
    default_message = "That step isn't available for this conversion right now."


class SelfExcluded(ConverterError):
    status_code, code = 403, "self_excluded"
    default_message = "You are self-excluded, so the booking code converter is disabled until your exclusion ends."
