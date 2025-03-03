import contextlib

from aiofiles.os import path as aiopath
from aiofiles.os import remove

from bot import (
    LOGGER,
    aria2,
    task_dict,
    task_dict_lock,
    user_data
)
from bot.core.config_manager import Config
from bot.helper.ext_utils.bot_utils import (
    bt_selection_buttons,
    new_task,
    sync_to_async,
)
from bot.helper.ext_utils.status_utils import MirrorStatus, get_task_by_gid
from bot.helper.telegram_helper.message_utils import (
    delete_message,
    send_message,
    send_status_message,
)


@new_task
async def select(_, message):
    if not Config.BASE_URL:
        await send_message(message, "Base URL not defined!")
        return
    user_id = message.from_user.id
    msg = message.text.split()
    if len(msg) > 1:
        gid = msg[1]
        task = await get_task_by_gid(gid)
        if task is None:
            await send_message(message, f"GID: <code>{gid}</code> Not Found.")
            return
    elif reply_to_id := message.reply_to_message_id:
        async with task_dict_lock:
            task = task_dict.get(reply_to_id)
        if task is None:
            await send_message(message, "This is not an active task!")
            return
    elif len(msg) == 1:
        msg = (
            "Reply to an active /cmd which was used to start the download or add gid along with cmd\n\n"
            + "This command mainly for selection incase you decided to select files from already added torrent. "
            + "But you can always use /cmd with arg `s` to select files before download start."
        )
        await send_message(message, msg)
        return

    if user_id not in (Config.OWNER_ID, task.listener.user_id) and (
        user_id not in user_data or not user_data[user_id].get("is_sudo")
    ):
        await send_message(message, "This task is not for you!")
        return
    if await sync_to_async(task.status) not in [
        MirrorStatus.STATUS_DOWNLOAD,
        MirrorStatus.STATUS_PAUSED,
        MirrorStatus.STATUS_QUEUEDL,
    ]:
        await send_message(
            message,
            "Task should be in download or pause (incase message deleted by wrong) or queued status (incase you have used torrent file)!",
        )
        return
    if task.name().startswith("[METADATA]") or task.name().startswith("Trying"):
        await send_message(message, "Try after downloading metadata finished!")
        return

    try:
        id_ = task.gid()
        if not task.queued:
            await sync_to_async(task.update)
            try:
                await sync_to_async(aria2.client.force_pause, id_)
            except Exception as e:
                LOGGER.error(
                    f"{e} Error in pause, this mostly happens after abuse aria2",
                )
        task.listener.select = True
    except Exception:
        await send_message(message, "This is not a bittorrent task!")
        return

    SBUTTONS = bt_selection_buttons(id_)
    msg = "Your download paused. Choose files then press Done Selecting button to resume downloading."
    await send_message(message, msg, SBUTTONS)


@new_task
async def confirm_selection(_, query):
    user_id = query.from_user.id
    data = query.data.split()
    message = query.message
    task = await get_task_by_gid(data[2])
    if task is None:
        await query.answer("This task has been cancelled!", show_alert=True)
        await delete_message(message)
        return
    if user_id != task.listener.user_id:
        await query.answer("This task is not for you!", show_alert=True)
    elif data[1] == "pin":
        await query.answer(data[3], show_alert=True)
    elif data[1] == "done":
        await query.answer()
        id_ = data[3]
    
        res = await sync_to_async(aria2.client.get_files, id_)
        for f in res:
            if f["selected"] == "false" and await aiopath.exists(f["path"]):
                with contextlib.suppress(Exception):
                    await remove(f["path"])
        if not task.queued:
            try:
                await sync_to_async(aria2.client.unpause, id_)
            except Exception as e:
                LOGGER.error(
                    f"{e} Error in resume, this mostly happens after abuse aria2. Try to use select cmd again!",
                )
        await send_status_message(message)
        await delete_message(message)
    else:
        await delete_message(message)
        await task.cancel_task()
