import discord, json, sqlite3
from discord import app_commands
from datetime import timedelta
from typing import List

from src import database
from src import utils

# connect to the database
con = sqlite3.connect('accounts.db'); con.row_factory = sqlite3.Row

# discord bot stuff
bot = discord.Client(intents=discord.Intents.default())
tree = app_commands.CommandTree(bot)
config = json.load(open('config.json'))

serviceList = []
is_everything_ready = False 

async def updateServices():
    global serviceList
    serviceList = await database.getServices(con)
    return

user_cooldown = []

@bot.event
async def on_ready():
    global is_everything_ready
    await tree.sync(guild=discord.Object(id=config["guild-id"]))
    
    await updateServices()
    print("Servicelist:", serviceList)
    
    is_everything_ready = True
    print("Logged in as {0.user}".format(bot))

async def service_autcom(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
    types = serviceList
    return [
        app_commands.Choice(name=service, value=service)
        for service in types if current.lower() in service.lower()
    ]

@tree.command(name = "delservice", description = "Supprimer un services", guild=discord.Object(id=config["guild-id"]))
@app_commands.autocomplete(service=service_autcom)
async def deleteservice(interaction: discord.Interaction, service: str):
    
    if not interaction.user.id in config['admins']:
        return await interaction.response.send_message(str(config['messages']['noperms']), ephemeral=True)
    
    if not is_everything_ready:
        return await interaction.response.send_message("Bot is starting.", ephemeral=True)

    db_res1 = await database.deleteService(con, service, serviceList)
    if db_res1:
        await updateServices()

    embd=discord.Embed(
        title=f"Delete Service",
        description=f'{"`✅` Service supprimé !" if db_res1 else "Error. Service doesnt exist."}',
        color=int(config['colors']['success']) if db_res1 else int(config['colors']['error'])
    )
    embd.set_footer(text=config['messages']['footer-msg'])
    
    return await interaction.response.send_message(embed=embd, ephemeral=True)

async def gen_cooldown(interaction: discord.Interaction):
    if interaction.user.id in config['admins']:
        return None
    
    userRoles = [role.id for role in interaction.user.roles]
    minCooldown = float("inf")
    
    for role in config["roles"]:
        if int(role["id"]) in userRoles and float(role["cooldown"]) < minCooldown:
            minCooldown = float(role["cooldown"])

    if not minCooldown == float("inf"):
        if interaction.user.id in user_cooldown:
            return app_commands.Cooldown(1, str(timedelta(seconds=minCooldown).total_seconds()))
        else:
            return None
    else:
        if interaction.user.id in user_cooldown:
            return app_commands.Cooldown(1, str(timedelta(seconds=config['roles'][0]["cooldown"]).total_seconds()))
        else:
            return None

@tree.command(name = "gen", description = "Générer un compte", guild=discord.Object(id=config["guild-id"]))
@app_commands.autocomplete(service=service_autcom)
@app_commands.checks.dynamic_cooldown(gen_cooldown)
async def gen(interaction: discord.Interaction, service: str):
    global user_cooldown
    
    if not is_everything_ready:
        return await interaction.response.send_message("Bot is starting.", ephemeral=True)
    
    if service not in serviceList:
        return await interaction.response.send_message(f'Invalid service.', ephemeral=True)

    if not interaction.user.id in config['admins'] and not interaction.channel_id in config["gen-channels"]:
        channel_list = [f"<#{channel}>" for channel in config["gen-channels"]]
        return await interaction.response.send_message(str(config['messages']['wrongchannel']) + ', '.join(channel_list), ephemeral=True)

    utl_res = await utils.does_user_meet_requirements(interaction.user.roles, config, service)
    if not interaction.user.id in config['admins'] and not utl_res:
        return await interaction.response.send_message(str(config['messages']['noperms']), ephemeral=True)

    # Cooldown
    if interaction.user.id in user_cooldown:
        user_cooldown.remove(interaction.user.id)
        embd=discord.Embed(title="Cooldown",description=f'`❌`Veuillez attendre la fin du cooldown.',color=config['colors']['error'])
        return await interaction.response.send_message(embed=embd, ephemeral=False)
    if interaction.user.id not in config['admins']:
        user_cooldown.append(interaction.user.id)

    success, account = await database.getAccount(con, service)
    if not success:
        user_cooldown.remove(interaction.user.id)
        return await interaction.response.send_message(f"There is no stock left.", ephemeral=True)
    else:
        
        channel = await interaction.user.create_dm()
        embd=discord.Embed(
            title=f"`✅` Service: ```{service}```",
            description=config['messages']['altsent'] + f"\n```{account['combo']}```",
            color=config['colors']['success']
        )
        embd.set_footer(text=config['messages']['footer-msg'],icon_url=interaction.user.avatar.url)

        embd2=discord.Embed(title=f"Compte Généré",description=f'`✅` {interaction.user.mention} **vien de générer un compte** `{service}`**. Vérifiez vos messages privés.**',color=config['colors']['success'])
        embd2.set_footer(text=config['messages']['footer-msg'],icon_url=interaction.user.avatar.url)
        embd2.set_image(url=config["generate-settings"]["gif-img-url"])

        await channel.send(embed=embd)
        return await interaction.response.send_message(embed=embd2, ephemeral=False)

@gen.error
async def gencmd_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.CommandOnCooldown):
        embd=discord.Embed(title="Cooldown",description=f'Veuillez attendre {(error.retry_after/60):.2f} minutes avant de générer a nouveau.',color=config['colors']['error'])
        await interaction.response.send_message(embed=embd, ephemeral=False)

@tree.command(name = "restock", description = "Restock des comptes", guild=discord.Object(id=config["guild-id"]))
@app_commands.autocomplete(service=service_autcom)
async def addaccounts(interaction: discord.Interaction, service: str, file: discord.Attachment):
    
    if not interaction.user.id in config['admins']:
        return await interaction.response.send_message(str(config['messages']['noperms']), ephemeral=True)

    if not is_everything_ready:
        return await interaction.response.send_message("Bot is starting.", ephemeral=True)
    
    if service not in serviceList:
        return await interaction.response.send_message(f'Invalid service.', ephemeral=True)
    
    try:
        if not str(file.filename).endswith(".txt"):
            return await interaction.response.send_message(f'You can only upload files with .txt extension', ephemeral=True)
    except:
        return await interaction.response.send_message(f'Error when checking file.', ephemeral=True)

    if file.size > config["maximum-file-size"]:
        return await interaction.response.send_message(f'Maximum file size: `{config["maximum-file-size"]} bytes`', ephemeral=True)
    content = await file.read()

    filtered_stock = []
    dec_cont = content.decode('utf-8')
    content = str(dec_cont).split("\n")
    for item in content:
        if len(item) > 2:
            filtered_stock.append(item)
    add_cnt,dupe_cnt = await database.addStock(con, service, filtered_stock, config['remove-capture-from-stock'])
    return await interaction.response.send_message(f'`{add_cnt}` comptes restock en service: `{service}` database. `{dupe_cnt}` dupes found.', ephemeral=True)

@tree.command(name = "create", description = "Crée un service", guild=discord.Object(id=config["guild-id"]))
async def createservice(interaction: discord.Interaction, servicename: str):
    
    if not interaction.user.id in config['admins']:
        return await interaction.response.send_message(str(config['messages']['noperms']), ephemeral=True)
    
    if not is_everything_ready:
        return await interaction.response.send_message("Bot is starting.", ephemeral=True)

    db_res1 = await database.createService(con, servicename, serviceList)
    if db_res1:
        await updateServices()

    embd=discord.Embed(
        title=f"Create Service",
        description=f'{"`✅` Service crée !" if db_res1 else "Error. Service already exists."}',
        color=int(config['colors']['success']) if db_res1 else int(config['colors']['error'])
    )
    embd.set_footer(text=config['messages']['footer-msg'])
    
    return await interaction.response.send_message(embed=embd, ephemeral=True)

@tree.command(name = "stock", description = "Regarder le stock", guild=discord.Object(id=config["guild-id"]))
async def stock(interaction: discord.Interaction):
    
    if not is_everything_ready:
        return await interaction.response.send_message("Bot is starting.", ephemeral=True)
    
    stock = await database.getStock(con, serviceList)
    if len(stock) <= 0:
        embd=discord.Embed(
            title=f"Stock - 0 services",
            description='There are no services to display',
            color=config['colors']['stock'])
        embd.set_footer(text=config['messages']['footer-msg'])
        return await interaction.response.send_message(embed=embd)

    filtered_stock = [] 
    for stk in stock:
        stk = (stk.split(':'))
        filtered_stock.append(f"**{stk[0]}**: `{stk[1]}`")

    embd=discord.Embed(
        title=f"Stock - {len(filtered_stock)}",
        description='\n'.join(filtered_stock),
        color=config['colors']['stock']
    )
    embd.set_footer(text=config['messages']['footer-msg'])
    
    return await interaction.response.send_message(embed=embd, ephemeral=config['stock-command-silent'])

bot.run(config['token'])