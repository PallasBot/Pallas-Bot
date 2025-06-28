import asyncio
from collections import defaultdict
from typing import Awaitable, Optional
from nonebot import on_message, on_request, get_bot, logger, get_driver
from nonebot.typing import T_State
from nonebot.rule import keyword, to_me, Rule
from nonebot.adapters import Bot, Event
from nonebot.adapters.onebot.v11 import GroupMessageEvent, GroupRequestEvent
from nonebot.adapters.onebot.v11 import MessageSegment, Message, permission, GroupMessageEvent
from nonebot.permission import Permission
from src.common.config import BotConfig, GroupConfig
import re
import random
import loguru
duel_player1 = defaultdict(list)
role_cache = defaultdict(lambda: defaultdict(str))
import time
import os
import random
from src.plugins.duel.gagController import  gagControlPanel

BLOCK_LIST=[]


async def am_I_admin(bot: Bot, event: GroupMessageEvent, state: T_State) -> bool:
    info = await get_bot(str(event.self_id)).call_api('get_group_member_info', **{
        'user_id': event.self_id,
        'group_id': event.group_id
    })
    role = info['role']
    role_cache[event.self_id][event.group_id] = role
    return role == 'admin' or role == 'owner'


async def am_at_admin(bot: Bot, event: GroupMessageEvent, state: T_State, duel_player: list) -> bool:
    info = await get_bot(str(event.self_id)).call_api('get_group_member_info', **{
        'user_id': duel_player[0],
        'group_id': event.group_id
    })
    role = info['role']
    role_cache[event.self_id][event.group_id] = role
    return role == 'admin' or role == 'owner'


async def is_duel_msg(bot: Bot, event: GroupMessageEvent, state: T_State) -> bool:
    curr_event = event.get_plaintext().strip()
    group_id=event.group_id# 根据群号判断是否处于黑名单群聊中,屏蔽响应
    if group_id in BLOCK_LIST:
        return False
    # loguru.logger.error(curr_event)
    if curr_event in ['牛牛决斗']:
        return True
    return False
async def is_victim_msg(bot: Bot, event: GroupMessageEvent, state: T_State) -> bool:
    msg_sender=event.get_user_id()
    group_id=event.group_id  # 根据群号判断是否处于黑名单群聊中,屏蔽响应
    if group_id in BLOCK_LIST:
        return False
    if gagControlPanel.check_victim(msg_sender):
        return True
    return False

victim_msg = on_message(
    priority=3,
    block=True,
    rule=Rule(is_victim_msg),
    permission=permission.GROUP
)


duel_msg = on_message(
    priority=3,
    block=True,
    rule=Rule(is_duel_msg),
    permission=permission.GROUP
)


async def duel(messagae_handle, bot: Bot, event: GroupMessageEvent, state: T_State):
    black_list = []  # 黑名单，以["QQ1", "QQ2"...]的形式填写，必败且时间延长至1-2小时
    raw_message = event.raw_message
    group_id=event.group_id
    group_id=str(group_id)

    pattern = re.compile(r"\[CQ:at,qq=(\d+)\]")
    defender = pattern.findall(raw_message)
    if len(defender) == 0:
        await messagae_handle.send("牛牛不可以这样使用...请输入\"牛牛决斗@决斗者\"来开启功能！")
        return
    elif len(defender) >= 2:
        await messagae_handle.send("不可以...那里...那里不可以进来这么多，一个就好...一个。")
        return
    defender=defender[0]
    match = re.search(r'user_id=(\d+)', str(event.sender))
    challenger = match.group(1)
    coolingDown=gagControlPanel.cooling_down(challenger) # 挑战者处于挑战冷却中
    gagControlPanel.flush_cooling_time(challenger,10)#挑战者添加10min的冷却时间
    inVictim=gagControlPanel.check_victim(challenger) # 挑战者正戴着口球

    defender_inVictim = gagControlPanel.check_victim(defender)
    #牛妈5.15新增的，因为另一个群出现了一个bug：决斗一个已经被带口球的人，如果触发了格挡会导致之前的口球时间也清零
    #下面的elif defender_inVictim同理

    if bot.self_id == challenger:
        pass
    elif bot.self_id == defender: #牛牛不能被选定为决斗对象
        await messagae_handle.send("不要让牛牛参加决斗啦...牛牛只想喝酒，呼...呼...")
        return
    elif challenger == defender: # 不能选定自己为决斗对象
        await messagae_handle.send("左脚踩右脚也不能上天哦。")
        return
    elif inVictim: # 挑战者正戴着口球
        await messagae_handle.send(f"塞着口球就安静一会吧~ 还有{inVictim}秒就能复仇啦!")
        return
    elif defender_inVictim: # 被挑战者带者口球
        if random.random() < 0.3:
            await messagae_handle.send("牛牛才不会允许乘人之危的事情！除非...除非你多试几次！")
        else:
            # 平分剩余时间
            await messagae_handle.send("当然，如果你想和Ta一起承受的话...")
            await asyncio.sleep(random.randint(1, 2))
            currTime = defender_inVictim/2#减少一半的时间
            gagControlPanel.add_victim(challenger,currTime/60,trigger_group=group_id) # 这里返回的是秒数啊!!!你忘了/60
            gagControlPanel.add_victim(defender,currTime/60)
            await messagae_handle.send(Message(f" [CQ:at,qq={challenger}] 决定承受 [CQ:at,qq={defender}] 一半的时长，请各位为他的勇气鼓掌。"))
        return
    elif coolingDown: # 冷却时间内再度挑战
        gagControlPanel.add_victim(challenger,1,trigger_group=group_id)
        await messagae_handle.send(f"我的勇士, 你还有{coolingDown}秒才能恢复哦, 先戴个口球喘口气吧~")
        return
    '''elif defender in black_list:
        gagControlPanel.add_victim(defender,80,trigger_group=group_id)
        return#等牛牛好了这句再改掉'''
    
    await messagae_handle.send(Message(f"决斗开始! [CQ:at,qq={challenger}] 对决 [CQ:at,qq={defender}] !"))
    
    victim=challenger
    master=defender
    
    challenge_success_rate=0.3 # 基础挑战胜率
    
    defender_token=gagControlPanel.get_user_token(defender) # 根据token确定获胜概率
    challenge_success_rate+=(defender_token*0.1)
    
    if challenger in black_list:
        challenge_success_rate = 0
        pass
    elif random.random() < challenge_success_rate or defender in black_list:
        victim=defender
        master=challenger
        if defender in black_list:
            challenge_success_rate = 1
    else :
        gagControlPanel.add_user_token(defender) # 挑战失败, 增加防守方惩罚token
    if victim in black_list:
        victim_time = 60+random.randint(0,60)
    else:
        victim_time=3+random.randint(1,5)
    
    await asyncio.sleep(random.randint(2, 5))
    await messagae_handle.send(Message(f"这是一场{int(challenge_success_rate*100)}%胜率的挑战! 胜负已分! [CQ:at,qq={victim}]乖乖带好口球, 大约{victim_time}分钟~"))


    if random.random() < 0.3 and victim not in black_list:
        typeChoince = random.random()
        counter_time = random.randint(3, 8)
        reactTime=counter_time+3+time.time()
        if typeChoince < 0.2:
            qte_key = random.choice(["同化", "偷袭", "锁定"])#同化
            await messagae_handle.send(Message(f"你很强大，但是...感受我的痛苦吧！请[CQ:at,qq={victim}]在{counter_time}秒内输入\"{qte_key}\"进行同化！"))
        elif typeChoince < 0.4:
            qte_key = random.choice(["反弹", "盾反", "反击"])#反弹
            await messagae_handle.send(Message(f"想要攻击...？可没那么容易！请[CQ:at,qq={victim}]在{counter_time}秒内输入\"{qte_key}\"进行反击！"))
        elif typeChoince < 0.6:
            qte_key = random.choice(["折射", "尖刺", "复仇"])#折射
            await messagae_handle.send(Message(f"这并不是你们的错...至少不应该是！请[CQ:at,qq={victim}]在{counter_time}秒内输入\"{qte_key}\"进行折射！"))
        elif typeChoince < 0.8:
            qte_key = random.choice(["格挡", "无效", "无敌"])#格挡
            await messagae_handle.send(Message(f"...就这样结束了么？不，绝不可能！请[CQ:at,qq={victim}]在{counter_time}秒内输入\"{qte_key}\"进行格挡！"))
        #  else:
        #      qte_key = random.choice(["减缓", "弱化", "防御"])#减缓
        #      await messagae_handle.send(Message(f"或许对你来说，惩罚并不需要...那么多。请[CQ:at,qq={victim}]在{counter_time}秒内输入\"{qte_key}\"进行弱化！把握住机会！"))"
        #  弱化功能之后再说
        gagControlPanel.edit_user_key(victim, 'qte_key', {qte_key:reactTime})
        
    
    gagControlPanel.add_victim(victim,victim_time,master,group_id)

async def process_defend(userID,messagae_handle):
    '''处理格挡QTE'''
    logger.success('defend')
    msg=f"[CQ:at,qq={userID}] 挡住了！我...愿米诺陶的神圣之盾与你同在。"
    gagControlPanel.add_victim(userID,-99999) #  增加负数时间以释放
    gagControlPanel.flush_cooling_time(userID,-99999) #  增加负数时间以释放
    await messagae_handle.send(Message(msg))
    return True

async def process_invincible(userID,messagae_handle):
    '''处理无敌QTE事件'''
    pass

async def process_assimilation(userID,messagae_handle):
    '''同化事件'''
    logger.success('process assi')
    curr_master = gagControlPanel.get_user_curr_master(userID)
    msg=f"[CQ:at,qq={userID}] 无法逃离审判，那么[CQ:at,qq={curr_master}] 也别想逃走！"
    msg_sender_victim_time = gagControlPanel.check_victim(userID)/60
    gagControlPanel.add_victim(curr_master,msg_sender_victim_time) #  除过60了，直接使用。
    await messagae_handle.send(Message(msg))
    return True

async def process_refraction(userID,messagae_handle):
    '''折射事件'''
    logger.success('process refraction')
    msg=f"[CQ:at,qq={userID}] 很聪明，知道谁伤害过他...是时候清算\"他们\"了。\n"
    await asyncio.sleep(random.randint(5, 10))
    curr_master = random.choice(gagControlPanel.get_user_masters(userID))
    msg_sender_victim_time = gagControlPanel.check_victim(userID)/60
    gagControlPanel.add_victim(userID,-99999) #  增加负数时间以释放
    gagControlPanel.flush_cooling_time(userID,-99999) #  增加负数时间以释放
    msg+=f"复仇之人...就是你 [CQ:at,qq={curr_master}]，承受他的痛苦吧。"
    gagControlPanel.add_victim(curr_master,msg_sender_victim_time) #  除过60了，直接使用。
    await messagae_handle.send(Message(msg))
    return True

async def  process_bounce(userID,message_handle):
    '''反弹事件'''
    logger.success(f'process bounce')
    curr_master = gagControlPanel.get_user_curr_master(userID)
    msg=f"[CQ:at,qq={userID}] 成功开出了反弹！那么受伤的就是[CQ:at,qq={curr_master}] 了！"
    msg_sender_victim_time = gagControlPanel.check_victim(userID)/60
    gagControlPanel.add_victim(userID,-99999) #  增加负数时间以释放
    gagControlPanel.flush_cooling_time(userID,-99999) #  增加负数时间以释放
    gagControlPanel.add_victim(curr_master,msg_sender_victim_time) #  除过60了，直接使用。
    await message_handle.send(Message(msg))
    return True

async def process_qte(userID,pressKey,messagae_handle): # 处理QTE事件
    
    #判断QTE按下的时机和触发的对象是否正确
    successKey=gagControlPanel.get_user_key(userID,'qte_key')
    gagControlPanel.edit_user_key(userID,'qte_key',False) # 获取后立即更新qte数据库
    if not successKey: # 没有对应的QTE
        return False
    checkKey=list(successKey.keys())[0]
    successTime=successKey[checkKey]
    logger.info(successKey)
    if time.time()>successTime: # 按太迟了
        return False
    if checkKey!=pressKey: # 敲错键了
        return False
    
    # QTE处理成功，开始处理QTE对应的事件
    
    qte_process_switcher={
        '同化':process_assimilation,
        '偷袭':process_assimilation,
        '锁定':process_assimilation,
        '反弹':process_bounce,
        '盾反':process_bounce,
        '反击':process_bounce,
        '折射':process_refraction,
        '尖刺':process_refraction,
        '复仇':process_refraction,
        '格挡':process_defend,
        '无效':process_defend,
        '无敌':process_defend
    }
    if pressKey not in qte_process_switcher.keys():#是还没实现的qte, 或者是出现了bug的qte
        logger.warning(f'{pressKey}QTE fail')
        return False
    if not qte_process_switcher[pressKey]:
        logger.warning(f'{pressKey}QTE not support yet')
        return False
    logger.success(f'process QTE -{pressKey}-')
    await qte_process_switcher[pressKey](userID,messagae_handle) # 使用userID触发QTE事件
    
    return True


async def victim_process(messagae_handle, bot: Bot, event: GroupMessageEvent, state: T_State):
    msgID=event.message_id
    rawmsg=event.raw_message
    match = re.search(r'user_id=(\d+)', str(event.sender))
    senderID = match.group(1)
    msg_sender=event.get_user_id()
    logger.info(f'get msg {rawmsg}')
    
    if len(rawmsg) <= 3 and await process_qte(senderID,rawmsg, messagae_handle):
        
        # 所有的qte事件在process_qte里面处理, 返回True后直接跳过本条消息的其他处理
        return
        
    if "啊呜" == rawmsg[-2:] or "汪" in rawmsg[-2:] or "喵" in rawmsg[-2:] or (len(rawmsg)>4 and 'u1s1' == rawmsg[:4]) :
        return
    
    try:
        await bot.call_api("delete_msg",message_id=msgID)
    except:
        pass
    
    cq_code=re.findall('\[CQ:.*?\]',rawmsg)
    cq_code_len=0
    if len(cq_code):
        cq_code_len=len(cq_code[0])
    
    if (len (rawmsg)>80+cq_code_len):
        await messagae_handle.send(f"太长了, 不行!")
        currTime = gagControlPanel.check_victim(senderID)/60
        currTime=int(currTime)
        newTime=currTime+random.randint(4,6)
        gagControlPanel.add_victim(senderID,newTime)
        if newTime > 15:
            await get_bot(str(event.self_id)).call_api('set_group_ban', **{
                'user_id': event.user_id,
                'group_id': event.group_id,
                'duration': newTime * 60
            })
            await messagae_handle.send(f"不要挑战牛牛的底线哦！")
        else:
            await messagae_handle.send(f"坏孩子要被惩罚的, 口球时长增加为{newTime}分钟!")
        return
    
    processed_msg=gagControlPanel.process_raw_data(rawmsg)
    
    describes = [f'叼着口球的[CQ:at,qq={msg_sender}]发出了含糊不清的声音:',
                     f'[CQ:at,qq={msg_sender}]好像含着些什么说:',
                     f'[CQ:at,qq={msg_sender}]叼着口球发出了些动静:',
                     f'[CQ:at,qq={msg_sender}]一边滴着口水一边说道:',
                     f'[CQ:at,qq={msg_sender}]有些气喘吁吁地说道:']
    msg=f'''{random.choice(describes)}
    {processed_msg}
    '''
    await messagae_handle.send(Message(msg))

@duel_msg.handle()
async def _(bot: Bot, event: GroupMessageEvent, state: T_State) -> bool:
    await duel(duel_msg, bot, event, state)

@victim_msg.handle()
async def _(bot: Bot, event: GroupMessageEvent, state: T_State) -> bool:
    await victim_process(duel_msg, bot, event, state)

