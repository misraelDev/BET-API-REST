from datetime import UTC, date, datetime, time, timedelta, timezone


def kickoff_hour_filter(target_date: date, hour: int) -> dict:
    mexico_city = timezone(timedelta(hours=-6))
    start = datetime.combine(target_date, time(hour), mexico_city).astimezone(UTC)
    end = start + timedelta(hours=1)
    return {
        "$expr": {
            "$and": [
                {
                    "$gte": [
                        {"$dateFromString": {"dateString": "$prediction.kickoff"}},
                        start,
                    ]
                },
                {
                    "$lt": [
                        {"$dateFromString": {"dateString": "$prediction.kickoff"}},
                        end,
                    ]
                },
            ]
        }
    }
