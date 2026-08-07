import asyncio
import unittest

from memory import (
    BENCHMARK_MEMORIES,
    ExtractionJob,
    MemoryRecord,
    MemoryWorkerAgent,
    RawMemoryCandidate,
    expand_memory_query,
    rank_memory_candidates,
)


def benchmark_candidates() -> list[RawMemoryCandidate]:
    return [
        RawMemoryCandidate(
            id=record.memory_id,
            document=record.document,
            metadata=record.metadata,
            distance=0.5,
        )
        for record in BENCHMARK_MEMORIES
    ]


class MemoryRankingTests(unittest.TestCase):
    def test_wedding_gift_recalls_white_polaroid(self) -> None:
        ranked = rank_memory_candidates(
            "我前女友后天要结婚了，我能送她什么？",
            benchmark_candidates(),
            top_k=2,
            min_score=0.0,
        )
        self.assertEqual(ranked[0].id, "benchmark_white_polaroid")

    def test_waiting_recalls_cold_milk_tea(self) -> None:
        ranked = rank_memory_candidates(
            "她以前是不是总在公司楼下等我下班？",
            benchmark_candidates(),
            top_k=2,
            min_score=0.0,
        )
        self.assertEqual(ranked[0].id, "benchmark_cold_milk_tea")

    def test_query_expansion_adds_hidden_association(self) -> None:
        expanded = expand_memory_query("前女友结婚送什么")
        self.assertIn("白色", expanded)
        self.assertIn("拍立得", expanded)


class FakeRepository:
    def __init__(self) -> None:
        self.saved: list[MemoryRecord] = []
        self.seeded = False

    async def seed_benchmark_memories(self) -> int:
        self.seeded = True
        return 4

    async def upsert(self, records) -> int:
        self.saved.extend(records)
        return len(records)

    async def search(self, *args, **kwargs):
        return []


class FakeExtractor:
    async def extract(self, *, user_id, user_message, assistant_message):
        return [
            MemoryRecord(
                user_id=user_id,
                entity="桂花拿铁",
                category="habit",
                context_summary="阿雾秋天喜欢喝少糖桂花拿铁。",
                emotional_weight=7,
            )
        ]


class MemoryWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_worker_extracts_after_dialogue(self) -> None:
        repository = FakeRepository()
        worker = MemoryWorkerAgent(
            repository,
            extractor=FakeExtractor(),
            queue_size=8,
        )
        await worker.start()
        self.assertTrue(repository.seeded)
        accepted = worker.enqueue(
            ExtractionJob(
                user_id="awu_001",
                user_message="秋天我喜欢桂花拿铁",
                assistant_message="我记住了，阿雾。",
                trace_id="req_test_memory",
            )
        )
        self.assertTrue(accepted)
        await asyncio.wait_for(worker._queue.join(), timeout=1.0)
        await worker.stop()
        self.assertEqual(repository.saved[0].entity, "桂花拿铁")


if __name__ == "__main__":
    unittest.main()

