"""NEXUS Tool Provider Interfaces for Dependency Injection.

Defines abstract base classes for external APIs and sensor providers,
allowing mock providers to be easily swapped with live production integrations.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from tools.schemas import (
    AmbulanceReservationInput,
    AmbulanceReservationOutput,
    AuditLogInput,
    AuditLogOutput,
    GeolocationOutput,
    HospitalStatusOutput,
    ImageAnalysisInput,
    ImageAnalysisOutput,
    IncidentReportsOutput,
    IncidentStatusUpdateInput,
    IncidentStatusUpdateOutput,
    NotificationInput,
    NotificationOutput,
    ResourceSearchInput,
    ResourceSearchOutput,
    RoutingInput,
    RoutingOutput,
    WeatherOutput,
)


class WeatherProvider(ABC):
    @abstractmethod
    async def get_weather(self, lat: float, lon: float) -> WeatherOutput:
        """Fetch meteorological metrics for latitude/longitude."""
        pass


class IncidentReportsProvider(ABC):
    @abstractmethod
    async def get_reports(self, lat: float, lon: float, radius_km: float) -> IncidentReportsOutput:
        """Fetch citizen and sensor reports in the incident vicinity."""
        pass


class ImageAnalysisProvider(ABC):
    @abstractmethod
    async def analyze_image(self, input_data: ImageAnalysisInput) -> ImageAnalysisOutput:
        """Perform multimodal visual flood depth and vehicle passability assessment."""
        pass


class GeolocationProvider(ABC):
    @abstractmethod
    async def geocode(self, query: str) -> GeolocationOutput:
        """Resolve landmark or address query to spatial coordinates."""
        pass


class RoutingProvider(ABC):
    @abstractmethod
    async def calculate_route(self, input_data: RoutingInput) -> RoutingOutput:
        """Compute safe topological routing bypassing compromised corridors."""
        pass


class ResourceSearchProvider(ABC):
    @abstractmethod
    async def search_resources(self, input_data: ResourceSearchInput) -> ResourceSearchOutput:
        """Query municipal emergency inventory for high-water and standard assets."""
        pass


class HospitalStatusProvider(ABC):
    @abstractmethod
    async def get_hospital_status(self, hospital_id: str) -> HospitalStatusOutput:
        """Query facility operational state, ER capacity, and ingress readiness."""
        pass


class NotificationProvider(ABC):
    @abstractmethod
    async def send_notification(self, input_data: NotificationInput) -> NotificationOutput:
        """Send operational alert to specified recipient channel."""
        pass


class AmbulanceReservationProvider(ABC):
    @abstractmethod
    async def reserve_ambulance(
        self, input_data: AmbulanceReservationInput
    ) -> AmbulanceReservationOutput:
        """Execute simulated reservation with idempotency guarantees."""
        pass


class IncidentStatusProvider(ABC):
    @abstractmethod
    async def update_status(
        self, input_data: IncidentStatusUpdateInput
    ) -> IncidentStatusUpdateOutput:
        """Transition incident operational state."""
        pass


class AuditLogProvider(ABC):
    @abstractmethod
    async def log_event(self, input_data: AuditLogInput) -> AuditLogOutput:
        """Record immutable audit event with cryptographic digest."""
        pass
