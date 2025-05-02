from datetime import datetime
import random

def generateFallbackKeywords(count: int = 50) -> list[str]:
    baseTopics = [
        "how to cook", "latest news about", "top 10 facts about", "history of", "guide to",
        "how to learn", "fun facts about", "benefits of", "future of", "causes of"
    ]
    randomSubjects = [
        "AI technology", "renewable energy", "space exploration", "the human brain",
        "golden retrievers", "volcanoes", "great wall of china", "black holes",
        "medieval castles", "famous inventions", "sustainable farming", "deep ocean exploration"
    ]
    today = datetime.now().strftime("%Y-%m-%d")
    return [f"{random.choice(baseTopics)} {random.choice(randomSubjects)} {today}" for _ in range(count)]
