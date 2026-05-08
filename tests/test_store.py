"""Test the parcel store module."""

import pytest

from custom_components.parcel_tracker.store import ParcelData


@pytest.mark.unit
class TestParcelData:
    """Tests for ParcelData dataclass."""

    def test_create_minimal(self):
        """Test creating ParcelData with minimal fields."""
        parcel = ParcelData(tracking_number="123", carrier="DHL")
        assert parcel.tracking_number == "123"
        assert parcel.carrier == "DHL"
        assert parcel.status == "registered"
        assert parcel.eta is None
        assert parcel.description is None

    def test_to_dict(self):
        """Test converting ParcelData to dict."""
        parcel = ParcelData(
            tracking_number="123",
            carrier="DHL",
            description="test",
        )
        d = parcel.to_dict()
        assert d["tracking_number"] == "123"
        assert d["carrier"] == "DHL"
        assert d["description"] == "test"

    def test_from_dict(self):
        """Test creating ParcelData from dict."""
        data = {
            "tracking_number": "456",
            "carrier": "UPS",
            "status": "in_transit",
            "eta": "2026-05-08",
        }
        parcel = ParcelData.from_dict(data)
        assert parcel.tracking_number == "456"
        assert parcel.carrier == "UPS"
        assert parcel.status == "in_transit"
        assert parcel.eta == "2026-05-08"

    def test_from_dict_ignores_unknown_fields(self):
        """Test that unknown fields are ignored."""
        data = {
            "tracking_number": "789",
            "carrier": "DPD",
            "unknown_field": "value",
        }
        parcel = ParcelData.from_dict(data)
        assert parcel.tracking_number == "789"

    def test_roundtrip(self):
        """Test dict roundtrip."""
        parcel = ParcelData(
            tracking_number="123",
            carrier="DHL",
            status="delivered",
            eta="2026-05-07",
            description="keyboard",
            registered_by="phone",
        )
        restored = ParcelData.from_dict(parcel.to_dict())
        assert restored.tracking_number == parcel.tracking_number
        assert restored.carrier == parcel.carrier
        assert restored.status == parcel.status
        assert restored.eta == parcel.eta
        assert restored.description == parcel.description
        assert restored.registered_by == parcel.registered_by
