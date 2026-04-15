"""Processing provider registration for DEM bathymetry review tools."""

from qgis.core import QgsProcessingProvider

from .algorithms.dem_bathy_review_algorithm import DemBathyReviewAlgorithm
from .algorithms.dem_bathy_grouped_review_algorithm import DemBathyGroupedReviewAlgorithm


class DemBathyReviewProvider(QgsProcessingProvider):
    """Registers DEM bathymetry review algorithms in the QGIS Processing toolbox."""

    def loadAlgorithms(self):
        """Load plugin algorithms into this provider."""
        self.addAlgorithm(DemBathyReviewAlgorithm())
        self.addAlgorithm(DemBathyGroupedReviewAlgorithm())

    def id(self):
        """Return provider identifier used by QGIS.

        Returns:
            str: Stable provider id.
        """
        return "dem_bathy_review"

    def name(self):
        """Return provider display name.

        Returns:
            str: Human-readable provider name.
        """
        return "DEM Bathymetry Review"

    def longName(self):
        """Return long provider name.

        Returns:
            str: Verbose provider name for UI contexts.
        """
        return self.name()
