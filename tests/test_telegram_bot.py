import pytest
import queue
from unittest.mock import MagicMock, AsyncMock, patch
from telegram_bot import agree_command, start, help_command, proxy_command, button_handler, verify_email_command
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
    telegram_bot.settings_mgr.settings.pop("user_agreed_12345", None)
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
    
    mock_update.message.text = "/pause"
    mock_update.effective_chat.id = 99999 # Unauthorized
    
    await proxy_command(mock_update, mock_context)
    
    assert telegram_bot.cmd_queue.empty()
    mock_update.message.reply_text.assert_called_with("Unauthorized.")


@pytest.mark.asyncio
async def test_proxy_command_status_allowed_for_non_admin(mock_update, mock_context, mock_config):
    telegram_bot.config = mock_config
    telegram_bot.cmd_queue = queue.Queue()

    mock_update.message.text = "/status"
    mock_update.effective_chat.id = 99999

    await proxy_command(mock_update, mock_context)

    assert not telegram_bot.cmd_queue.empty()
    cmd, args, chat_id = telegram_bot.cmd_queue.get()
    assert cmd == "/status"
    assert chat_id == 99999
    mock_update.message.reply_text.assert_called_with("Command /status queued.")


@pytest.mark.asyncio
async def test_button_handler_agree_shows_main_menu(mock_context):
    query = MagicMock()
    query.data = "agree_12345"
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    query.message.chat.id = 12345
    mock_context.bot.send_message = AsyncMock()

    update = MagicMock()
    update.callback_query = query

    await button_handler(update, mock_context)

    query.answer.assert_called_once()
    query.edit_message_text.assert_called_once()
    assert "Trading Bot Connected" in query.edit_message_text.call_args.args[0]
    assert query.edit_message_text.call_args.kwargs["reply_markup"] is not None
    mock_context.bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_button_handler_agree_falls_back_to_new_message(mock_context):
    query = MagicMock()
    query.data = "agree_12345"
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock(side_effect=RuntimeError("cannot edit"))
    query.message.chat.id = 12345
    mock_context.bot.send_message = AsyncMock()

    update = MagicMock()
    update.callback_query = query

    await button_handler(update, mock_context)

    query.answer.assert_called_once()
    mock_context.bot.send_message.assert_called_once()
    assert "Trading Bot Connected" in mock_context.bot.send_message.call_args.kwargs["text"]


@pytest.mark.asyncio
async def test_verify_email_command_success(mock_update, mock_context, mock_config):
    telegram_bot.config = mock_config
    mock_context.args = ["user@example.com"]

    with patch.object(telegram_bot.db, "request_email_verification", return_value="123456"):
        with patch("telegram_bot.EmailService") as mock_email_service:
            mock_email_service.return_value.send_verification_email.return_value = True

            await verify_email_command(mock_update, mock_context)

    mock_update.message.reply_text.assert_called()
    assert "Verification Email Sent" in mock_update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_verify_email_command_failure(mock_update, mock_context, mock_config):
    telegram_bot.config = mock_config
    mock_context.args = ["user@example.com"]

    with patch.object(telegram_bot.db, "request_email_verification", return_value="123456"):
        with patch("telegram_bot.EmailService") as mock_email_service:
            mock_email_service.return_value.send_verification_email.return_value = False

            await verify_email_command(mock_update, mock_context)

    mock_update.message.reply_text.assert_called()
    assert "EMAIL_CONFIRM_WEBHOOK_URL" in mock_update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_agree_command_sends_menu(mock_update, mock_context):
    telegram_bot.settings_mgr.settings.pop("user_agreed_12345", None)

    await agree_command(mock_update, mock_context)

    assert telegram_bot.settings_mgr.get("user_agreed_12345") is True
    assert mock_update.message.reply_text.call_count == 2
    assert "Agreement recorded" in mock_update.message.reply_text.call_args_list[0].args[0]
    assert "Trading Bot Connected" in mock_update.message.reply_text.call_args_list[1].args[0]
