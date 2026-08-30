from app.collectors.base import BaseJobCollector, CollectorError, PublicJobNotFound
from app.collectors.generic import GenericCareerPageCollector
from app.collectors.greenhouse import GreenhouseCollector
from app.collectors.lever import LeverCollector
from app.collectors.workday import WorkdayCollector

COLLECTORS = {
    "greenhouse": GreenhouseCollector,
    "lever": LeverCollector,
    "workday": WorkdayCollector,
    "generic": GenericCareerPageCollector,
    "custom": GenericCareerPageCollector,
}

__all__ = [
    "BaseJobCollector",
    "CollectorError",
    "PublicJobNotFound",
    "GenericCareerPageCollector",
    "GreenhouseCollector",
    "LeverCollector",
    "WorkdayCollector",
    "COLLECTORS",
]
