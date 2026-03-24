import pytest
import queue
from unittest.mock import MagicMock, AsyncMock, patch
from telegram_bot import start, help_command, proxy_command
import telegram_bot # to get global variables if needed

@pytest.fixture
def mock_update():
    update = MagicMock()
    update.effective_user.id = 12345
    update.effective_user.username = "tester"
    update.effective_user.first_name = "Test"
    update.effective_chat.id = 12345
    update.message.text = "/status"
    update.message.reply_text = AsyncMock()
    return update

@pytest.fixture
def mock_context():
    return MagicMock()

@pytest.mark.asyncio
async def test_start_command(mock_update, mock_context):
    await start(mock_update, mock_context)
    mock_update.message.reply_text.assert_called()
    assert "IMPORTANT LEGAL" in mock_update.message.reply_text.call_args[0][0]

@pytest.mark.asyncio
async def test_help_command(mock_update, mock_context):
    await help_command(mock_update, mock_context)
    # Check if a long help message was sent
    mock_update.message.reply_text.assert_called()
    assert "Available Commands" in mock_update.message.reply_text.call_args[0][0]

@pytest.mark.asyncio
async def test_proxy_command_authorized(mock_update, mock_context, mock_config):
    # Set globals for telegram_bot module
    telegram_bot.config = mock_config
    telegram_bot.cmd_queue = queue.Queue()
    
    mock_update.message.text = "/status"
    mock_update.effective_chat.id = 12345 # Authorized in mock_config
    
    await proxy_command(mock_update, mock_context)
    
    # Check if command put in queue
    assert not telegram_bot.cmd_queue.empty()
    cmd, args, chat_id = telegram_bot.cmd_queue.get()
    assert cmd == "/status"
    assert chat_id == 12345
    mock_update.message.reply_text.assert_called_with("Command /status queued.")

@pytest.mark.asyncio
async def test_proxy_command_unauthorized(mock_update, mock_context, mock_config):
    telegram_bot.config = mock_config
    telegram_bot.cmd_queue = queue.Queue()
    
    mock_update.message.text = "/status"
    mock_update.effective_chat.id = 99999 # Unauthorized
    
    await proxy_command(mock_update, mock_context)
    
    assert telegram_bot.cmd_queue.empty()
    mock_update.message.reply_text.assert_called_with("Unauthorized.")
