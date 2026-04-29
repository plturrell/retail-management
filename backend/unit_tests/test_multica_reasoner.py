import pytest
from unittest.mock import MagicMock, patch
from typing import Any
import sys
import os

# Ensure multica is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../multica')))

from agent import MulticaAgent

# Mock Snowflake Session
class MockSession:
    def sql(self, query: str):
        mock_df = MagicMock()
        # Ensure it returns a non-empty dataframe mock
        mock_df.to_pandas.return_value.empty = False
        mock_df.to_pandas.return_value.to_json.return_value = '[{"SKU_CODE": "TEST-01", "QTY_ON_HAND": 2}]'
        return mock_df

class MockMessage:
    def __init__(self, content):
        self.content = content

class MockChoice:
    def __init__(self, content):
        self.message = MockMessage(content)

class MockResponse:
    def __init__(self, content):
        self.choices = [MockChoice(content)]

@patch('agent.OpenAI')
@patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key-mock"})
def test_multica_reasoner_parses_think_block(mock_openai):
    # Setup mock OpenAI client
    mock_client = MagicMock()
    mock_openai.return_value = mock_client
    
    # Simulate a DeepSeek Reasoner response with a massive <think> block
    simulated_response = """<think>
Here is my deep reasoning process.
I see that TEST-01 has only 2 items left.
The user also provided recent TiDB transactions showing high velocity.
Therefore, this is a critical situation.
I will structure my JSON accordingly.
</think>

{
    "status": "critical",
    "summary": "TEST-01 is dangerously low based on recent TiDB ledger velocity.",
    "priority_replenishments": ["TEST-01"]
}
"""
    mock_client.chat.completions.create.return_value = MockResponse(simulated_response)
    
    session = MockSession()
    agent = MulticaAgent(session)
    
    tidb_ledger_data = "2023-10-25 10:00:00 - TEST-01 - Sold 5 units"
    
    response = agent.evaluate_inventory_health(store_id="STORE-A", low_stock_threshold=5, recent_transactions=tidb_ledger_data)
    
    # Verify OpenAI was called correctly
    mock_client.chat.completions.create.assert_called_once()
    call_args = mock_client.chat.completions.create.call_args[1]
    assert call_args["model"] == "deepseek-reasoner"
    assert "Recent Real-Time Transactions (TiDB Ledger):" in call_args["messages"][0]["content"]
    assert "2023-10-25 10:00:00 - TEST-01 - Sold 5 units" in call_args["messages"][0]["content"]
    
    # Verify the JSON was parsed perfectly despite the <think> block
    assert response.parsed_json is not None
    assert response.parsed_json["status"] == "critical"
    assert "priority_replenishments" in response.parsed_json
    assert response.parsed_json["priority_replenishments"] == ["TEST-01"]
    assert response.error is None
