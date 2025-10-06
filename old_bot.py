import os
from discord import File
import io
import csv
import aiosqlite
from typing import List, Tuple, Dict
import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import Button, View, Modal, TextInput

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix='/', intents=intents)
role_code_lists: Dict[str, List[Tuple[int, discord.Role, str]]] = {}

class RoleButton(Button):
    def __init__(self, role: discord.Role):
        super().__init__(label=role.name, style=discord.ButtonStyle.primary)
        self.role = role

    async def callback(self, interaction: discord.Interaction):
        embed = discord.Embed(title="身份組操作", color=discord.Color.blue())
        if self.role in interaction.user.roles:
            await interaction.user.remove_roles(self.role)
            embed.description = f"已移除「{self.role.name}」身份組！"
        else:
            await interaction.user.add_roles(self.role)
            embed.description = f"已領取「{self.role.name}」身份組！"
        await interaction.response.send_message(embed=embed, ephemeral=True)

class CodeModal(Modal):
    def __init__(self):
        super().__init__(title="輸入代碼")
        self.add_item(TextInput(label="請輸入代碼", placeholder="在這裡輸入代碼..."))

    async def on_submit(self, interaction: discord.Interaction):
        user_input = self.children[0].value
        role_found = False
        embed = discord.Embed(title="代碼處理結果", color=discord.Color.blue())
        for list_name, entries in role_code_lists.items():
            for _, role, code in entries:
                if user_input == code:
                    role_found = True
                    if role in interaction.user.roles:
                        await interaction.user.remove_roles(role)
                        embed.description = f"已移除「{role.name}」身份組！"
                    else:
                        await interaction.user.add_roles(role)
                        embed.description = f"已領取「{role.name}」身份組！"
                    break
            if role_found:
                break
        if not role_found:
            embed.description = "代碼不存在"
        await interaction.response.send_message(embed=embed, ephemeral=True)

class RoleView(View):
    def __init__(self, roles: List[discord.Role]):
        super().__init__(timeout=None)
        for role in roles:
            self.add_item(RoleButton(role))

class CodeButton(Button):
    def __init__(self):
        super().__init__(label="輸入代碼", style=discord.ButtonStyle.primary)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(CodeModal())

class CodeView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(CodeButton())

async def init_db(guild_id: int):
    db_name = f'role_codes_{guild_id}.db'  
    async with aiosqlite.connect(db_name) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS role_code_lists (
                list_name TEXT,
                role_id INTEGER,
                code TEXT
            )
        ''')
        await db.commit()

async def load_role_code_lists(guild_id: int):
    global role_code_lists
    role_code_lists = {}
    db_name = f'role_codes_{guild_id}.db'  
    async with aiosqlite.connect(db_name) as db:
        async with db.execute('SELECT list_name, role_id, code FROM role_code_lists') as cursor:
            async for row in cursor:
                list_name, role_id, code = row
                role = discord.utils.get(bot.guilds[0].roles, id=role_id)
                if role:
                    if list_name not in role_code_lists:
                        role_code_lists[list_name] = []
                    role_code_lists[list_name].append((len(role_code_lists[list_name]) + 1, role, code))

async def save_role_code_list(list_name: str, role: discord.Role, code: str):
    async with aiosqlite.connect('role_codes.db') as db:
        await db.execute('INSERT INTO role_code_lists (list_name, role_id, code) VALUES (?, ?, ?)', (list_name, role.id, code))
        await db.commit()

async def delete_role_code_list(list_name: str):
    async with aiosqlite.connect('role_codes.db') as db:
        await db.execute('DELETE FROM role_code_lists WHERE list_name = ?', (list_name,))
        await db.commit()

async def delete_role_code_entry(list_name: str, code: str):
    async with aiosqlite.connect('role_codes.db') as db:
        await db.execute('DELETE FROM role_code_lists WHERE list_name = ? AND code = ?', (list_name, code))
        await db.commit()

@bot.event
async def on_ready():
    print(f'{bot.user} 已上線！')
    await init_db(bot.guilds[0].id)  
    await load_role_code_lists(bot.guilds[0].id)  
    try:
        await bot.tree.sync()
        print('指令同步成功！')
    except Exception as e:
        print(f'指令同步失敗: {e}')

def is_admin():
    async def predicate(interaction: discord.Interaction):
        return interaction.user.guild_permissions.administrator
    return app_commands.check(predicate)

@bot.tree.command(name="give_role", description="派發身份組到指定的DC帳號(使用者名稱)")
@is_admin()
async def give_role(interaction: discord.Interaction, role_name: str, usernames: str):
    await interaction.response.defer(ephemeral=True) 
    role = discord.utils.get(interaction.guild.roles, name=role_name.strip())
    embed = discord.Embed(title="身份組派發結果", color=discord.Color.blue())
    
    if not role:
        embed.description = f"無效的身份組: {role_name}"
        await interaction.followup.send(embed=embed, ephemeral=True)
        return
    
    username_list = [username.strip() for username in usernames.split(',')]
    failed_users = []
    success_count = 0

    for username in username_list:
        user = interaction.guild.get_member_named(username)
        if user:
            try:
                await user.add_roles(role)
                success_count += 1
            except discord.Forbidden:
                failed_users.append(username)
        else:
            failed_users.append(username)

    embed.description = f"已成功將身份組 '{role_name}' 派發給 {success_count} 位用戶。"
    if failed_users:
        embed.description += f"\n以下用戶未能派發身份組: {', '.join(failed_users)}"
    
    await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="give_role_from_csv", description="從CSV派發身份組到指定的DC帳號")
@is_admin()
async def give_role_from_csv(interaction: discord.Interaction, role_name: str, file: discord.Attachment):
    await interaction.response.defer(ephemeral=True)  
    role = discord.utils.get(interaction.guild.roles, name=role_name.strip())
    embed = discord.Embed(title="身份組派發結果", color=discord.Color.blue())
    
    if not role:
        embed.description = f"無效的身份組: {role_name}"
        await interaction.followup.send(embed=embed, ephemeral=True)
        return
    
    csv_data = await file.read()
    csv_text = csv_data.decode('utf-8')
    
    csv_reader = csv.reader(io.StringIO(csv_text))
    failed_users = []
    success_count = 0
    
    for row in csv_reader:
        if len(row) == 0:
            continue
        
        username = row[0].strip()
        user = interaction.guild.get_member_named(username)
        
        if user:
            try:
                await user.add_roles(role)
                success_count += 1
            except discord.Forbidden:
                failed_users.append(username)
        else:
            failed_users.append(username)

    embed.description = f"已成功將身份組 '{role_name}' 派發給 {success_count} 位用戶。"
    if failed_users:
        embed.description += f"\n以下用戶未能派發身份組: {', '.join(failed_users)}"
    
    await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="create_list", description="建立身份組和代碼的清單")
@is_admin()
async def create_list(interaction: discord.Interaction, list_name: str):
    global role_code_lists
    embed = discord.Embed(title="清單建立結果", color=discord.Color.blue())
    
    if list_name in role_code_lists:
        embed.description = f"清單 '{list_name}' 已存在。"
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    role_code_lists[list_name] = []
    embed.description = f"清單 '{list_name}' 已建立。"
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="add_entry", description="新增身份組和代碼的組合")
@is_admin()
async def add_entry(interaction: discord.Interaction, list_name: str, entry: str):
    global role_code_lists
    embed = discord.Embed(title="新增組合結果", color=discord.Color.blue())
    
    try:
        role_name, code = entry.split(":")
        role = discord.utils.get(interaction.guild.roles, name=role_name.strip())
        if role:
            if list_name not in role_code_lists:
                role_code_lists[list_name] = []
            for entries in role_code_lists.values():
                if any(c == code.strip() for _, _, c in entries):
                    embed.description = "代碼已存在於其他清單中。"
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    return
            role_code_lists[list_name].append((len(role_code_lists[list_name]) + 1, role, code.strip()))
            await save_role_code_list(list_name, role, code.strip())
            embed.description = f"已新增組合到 '{list_name}': {role.name} -> 代碼: {code.strip()}"
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            embed.description = f"無效的身份組: {role_name}"
            await interaction.response.send_message(embed=embed, ephemeral=True)
    except ValueError:
        embed.description = "無效輸入。格式應該是 '身份組:代碼'。"
        await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="remove_entry", description="刪除身份組和代碼的組合")
@is_admin()
async def remove_entry(interaction: discord.Interaction, list_name: str, entry_number: int):
    global role_code_lists
    embed = discord.Embed(title="刪除組合結果", color=discord.Color.blue())
    
    if list_name not in role_code_lists:
        embed.description = f"清單 '{list_name}' 不存在。"
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    if entry_number < 1 or entry_number > len(role_code_lists[list_name]):
        embed.description = f"無效的組合編號: {entry_number}"
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    removed_entry = role_code_lists[list_name].pop(entry_number - 1)
    await delete_role_code_entry(list_name, removed_entry[2])
    embed.description = f"已刪除組合從 '{list_name}': {removed_entry[1].name} -> 代碼: {removed_entry[2]}"
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="delete_list", description="刪除清單")
@is_admin()
async def delete_list(interaction: discord.Interaction, list_name: str):
    global role_code_lists
    embed = discord.Embed(title="刪除清單結果", color=discord.Color.blue())
    
    if list_name in role_code_lists:
        del role_code_lists[list_name]
        await delete_role_code_list(list_name)
        embed.description = f"清單 '{list_name}' 已刪除。"
        await interaction.response.send_message(embed=embed, ephemeral=True)
    else:
        embed.description = f"清單 '{list_name}' 不存在。"
        await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="build_code", description="用代碼建立按鈕")
@is_admin()
async def build_code(interaction: discord.Interaction):
    embed = discord.Embed(title="輸入代碼", color=discord.Color.blue())
    
    if not role_code_lists:
        embed.description = "目前沒有任何清單。"
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    view = CodeView()
    embed.description = "請點擊按鈕並輸入代碼以領取身份組。"
    await interaction.response.send_message(embed=embed, view=view)

@bot.tree.command(name="check_list", description="查看清單")
@is_admin()
async def check_list(interaction: discord.Interaction, list_name: str = None):
    embed = discord.Embed(title="查看清單", color=discord.Color.blue())
    
    if list_name:
        if list_name not in role_code_lists or not role_code_lists[list_name]:
            embed.description = f"清單 '{list_name}' 不存在或為空。"
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        list_details = [f"{seq}. {role.name} -> 代碼: {code}" for seq, role, code in role_code_lists[list_name]]
        message_parts = []
        current_part = f"清單 '{list_name}' 如下：\n"
        
        for detail in list_details:
            if len(current_part) + len(detail) > 1900:
                message_parts.append(current_part)
                current_part = ""
            current_part += f"{detail}\n"
        
        if current_part:
            message_parts.append(current_part)

        embed.description = "正在發送清單..."
        await interaction.response.send_message(embed=embed, ephemeral=True)

        for part in message_parts:
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(part, ephemeral=True)
                else:
                    await interaction.response.send_message(part, ephemeral=True)
            except discord.errors.Forbidden:
                await interaction.user.send(part)
    else:
        if not role_code_lists:
            embed.description = "目前沒有任何清單。"
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        list_names = "\n".join(role_code_lists.keys())
        embed.description = f"目前的清單有：\n{list_names}"
        await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="build", description="建立領取身份組按鈕")
@is_admin()
async def create_role_buttons(interaction: discord.Interaction, role_names: str):
    roles = []
    invalid_roles = []
    embed = discord.Embed(title="建立按鈕結果", color=discord.Color.blue())

    for role_name in role_names.split(','):
        role = discord.utils.get(interaction.guild.roles, name=role_name.strip())
        if role:
            roles.append(role)
        else:
            invalid_roles.append(role_name.strip())

    if invalid_roles:
        embed.description = f"無效的身份組: {', '.join(invalid_roles)}"
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    if not roles:
        embed.description = "沒有有效的身份組。"
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    view = RoleView(roles)
    embed.description = "請點擊按鈕領取或移除身份組"
    await interaction.response.send_message(embed=embed, view=view)

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    embed = discord.Embed(title="錯誤", color=discord.Color.red())
    
    if isinstance(error, app_commands.errors.CheckFailure):
        embed.description = "此指令限管理員使用。"
    else:
        embed.description = f"發生未知錯誤: {error}"
    
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)
    
    try:
        await interaction.followup.send(embed=embed, ephemeral=True)
    except Exception as e:
        print(f"Failed to send error response: {str(e)}")
    
        
bot.run(os.getenv('TOKEN'))

