"""Tests for runtime performance tuning heuristics."""

from swampcastle.tuning import suggest_onnx_tuning


def test_suggest_onnx_tuning_for_large_machine():
    tuning = suggest_onnx_tuning(cpu_count=32, total_memory_bytes=24 * 1024**3)
    assert tuning == {
        "onnx_intra_op_threads": 16,
        "onnx_inter_op_threads": 1,
        "embed_batch_size": 256,
    }


def test_suggest_onnx_tuning_for_small_machine():
    tuning = suggest_onnx_tuning(cpu_count=4, total_memory_bytes=4 * 1024**3)
    assert tuning == {
        "onnx_intra_op_threads": 2,
        "onnx_inter_op_threads": 1,
        "embed_batch_size": 64,
    }
