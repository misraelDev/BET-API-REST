from app.shared.record_service import (
    NBA_CONFIG,
    RecordBasedPredictionService,
)
from app.sports.nba.public_client import PublicBasketballClient


class NbaPredictionService(RecordBasedPredictionService):
    def __init__(self, client: PublicBasketballClient) -> None:
        super().__init__(client, NBA_CONFIG)
