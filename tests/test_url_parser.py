"""Test the URL parser module."""

import pytest

from custom_components.parcel_tracker.url_parser import (
    build_tracking_url,
    parse_tracking_url,
)


@pytest.mark.unit
class TestParseTrackingUrl:
    """Tests for parse_tracking_url."""

    def test_dhl_url(self):
        """Test DHL URL parsing."""
        url = "https://www.dhl.de/de/privatkunden/dhl-sendungsverfolgung.html?piececode=1234567890123456"
        carrier, number = parse_tracking_url(url)
        assert carrier == "DHL"
        assert number == "1234567890123456"

    def test_dpd_url(self):
        """Test DPD URL parsing."""
        url = "https://tracking.dpd.de/status/de_DE/parcel/12345678901234"
        carrier, number = parse_tracking_url(url)
        assert carrier == "DPD"
        assert number == "12345678901234"

    def test_ups_url(self):
        """Test UPS URL parsing."""
        url = "https://www.ups.com/track?tracknum=1Z12345E6605272234"
        carrier, number = parse_tracking_url(url)
        assert carrier == "UPS"
        assert number == "1Z12345E6605272234"

    def test_hermes_url(self):
        """Test Hermes URL parsing."""
        url = "https://www.myhermes.de/empfangen/sendungsverfolgung/sendungsinformation#12345678901234"
        carrier, number = parse_tracking_url(url)
        assert carrier == "Hermes"
        assert number == "12345678901234"

    def test_gls_url(self):
        """Test GLS URL parsing."""
        url = "https://gls-group.com/DE/de/paketverfolgung?match=A1B2C3D4E5F6"
        carrier, number = parse_tracking_url(url)
        assert carrier == "GLS"
        assert number == "A1B2C3D4E5F6"

    def test_fedex_url(self):
        """Test FedEx URL parsing."""
        url = "https://www.fedex.com/fedextrack/?trknbr=123456789012"
        carrier, number = parse_tracking_url(url)
        assert carrier == "FedEx"
        assert number == "123456789012"

    def test_unknown_url(self):
        """Test unknown URL returns None."""
        url = "https://example.com/tracking/12345"
        carrier, number = parse_tracking_url(url)
        assert carrier is None
        assert number is None


@pytest.mark.unit
class TestBuildTrackingUrl:
    """Tests for build_tracking_url."""

    def test_dhl_url(self):
        """Test DHL URL generation."""
        url = build_tracking_url("DHL", "1234567890123456")
        assert "1234567890123456" in url
        assert "dhl.de" in url

    def test_unknown_carrier(self):
        """Test unknown carrier returns None."""
        url = build_tracking_url("UnknownCarrier", "123")
        assert url is None
