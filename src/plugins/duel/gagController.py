import random
import time
import os
import json
import pymongo


class gagController:
    def __init__(self):
        
        # 初始化数据库连接
        
        self.mongo_client = pymongo.MongoClient('127.0.0.1', 27017, w=0)

        self.mongo_db = self.mongo_client['PallasBot']
        
        self.user_mongo = self.mongo_db['users']

        pass
    

    def check_timer(self, timer_key, userID:str):
        '''检测timer_key对应的计时器, 如果包含的时间大于当前时间,返回计时器时间-当前时间, 单位是秒, 否则返回0'''
        currTime=time.time()
        userInfo=self.user_mongo.find_one({'user_id':userID,timer_key:{'$gt':currTime}})
        if userInfo:
            return int(userInfo[timer_key]-currTime)
        return 0

    def upgrade_timer(self, timer_key, newKey, userID:str):
        '''使timer_key对应的值变为newKey, 如果timer_key不存在则新增记录. 
        没有限制newKey的类型, 但请尽量只将这个方法用于更新计时器'''        
        self.user_mongo.update_one({'user_id':userID},{"$set":{timer_key:newKey}},True)

    def cooling_down(self, userID:str):
        '''检测用户的挑战冷却计时器'''
        return self.check_timer('cooling_until', userID)

    def flush_cooling_time(self,  userID:str, cooling_gap):
        '''使用传入的gap刷新用户的挑战冷却计时器, 注意这里的gap以分钟为单位'''
        self.upgrade_timer('cooling_until', time.time()+cooling_gap*60, userID)
        pass


    def add_victim(self,  userID:str, gap:float, trigger_user:str='', trigger_group:str=""):
        '''添加一个口球受害者, gap以分钟计, trigger_user为触发添加事件的用户, 数据库会一并记录'''
        self.user_mongo.update_one({'user_id':userID},{"$set":{'defend_token':0}},True) # 防御tokne的清零逻辑暂时不拎出来了, 整合在add里面一起 在被塞上口球的时候清空用户的防御惩罚点数
        self.upgrade_timer('victim_until', time.time()+gap*60, userID)
        
        
        #####记录当前用户的主人们########
        
        if not trigger_user or trigger_user==userID: # 触发用户未设置, 或者触发用户是自己, 直接返回
            pass
        else:
            userMasters=self.get_user_key(userID,'masters') # 获取曾经当过当前用户主人的字段
            if not userMasters or not isinstance(userMasters,list):
                userMasters=[trigger_user]
            else:
                userMasters.append(trigger_user)
            userMasters=list(set(userMasters)) # 使用set为主人列表去重
        
            self.edit_user_key(userID,'masters',userMasters)# 更新曾经当过当前用户主人的字段
            self.edit_user_key(userID,'curr_master',trigger_user)# 更新当前用户的现任主人
        ########

        ######给rbq身上加正字#########
        curr_collect=self.get_user_key(userID,'rbq_cont')
        
        if not curr_collect or not isinstance(curr_collect,dict):
            curr_collect={}
        
        if trigger_group not in curr_collect:
            curr_collect[trigger_group]=0
        
        if trigger_group: # 只在触发群组设定时写入数据库
            curr_collect[trigger_group]+=1
            self.edit_user_key(userID,'rbq_cont',curr_collect)


        ######

    def get_group_rbq_list(self,groupID:str)->dict:
        '''获取群内绒布球统计'''
        db_members=self.user_mongo.find({})
        result={}
        for member in db_members:
            userID=member['user_id']
            rbqCont=member['rbq_cont']
            if groupID not in rbqCont:
                continue
            result[userID]=rbqCont[groupID]
        return result
    def get_rbq_cont(self,userID)->dict:
        '''获取某个绒布球的群统计'''
        userInfo=self.get_user_key(userID,'rbq_cont')
        return userInfo


    def get_user_curr_master(self,userID:str)->str:
        '''获取当前用户的现任主人(最近一个给当前用户戴口球的人), 没有则返回空字符串'''
        masterID=self.get_user_key(userID,'curr_master')
        if not masterID:
            return ''
        return masterID
    def get_user_masters(self,userID:str)->list:
        '''获取所有给当前用户戴过口球的主人列表'''
        masterIDs=self.get_user_key(userID,'masters')
        if not masterIDs:
            return []
        return masterIDs    
    
    def check_victim(self,  userID:str):
        '''检查用户是否正塞着口球, 如果是则返回剩余秒数'''
        return self.check_timer('victim_until', userID)

    def edit_user_key(self, userID:str,keyType,keyValue):
        '''和upgrade_timer执行逻辑一致, 新增或者修改数据库中的用户记录请使用本接口'''
        self.user_mongo.update_one({'user_id':userID},{"$set":{keyType:keyValue}},True)

    def get_user_key(self, userID:str,keyType): 
        '''获取数据库中用户的某项数据, 如果数据不存在则返回False'''
        userInfo=self.user_mongo.find_one({'user_id':userID})
        if userInfo and keyType in userInfo:
            return userInfo[keyType]
        return False

    def add_user_token(self, userID:str):
        '''为防守成功的用户增加惩罚token'''
        token=self.user_mongo.find_one({'user_id':userID,'defend_token':{'$gt':0}})
        if not token:
            self.user_mongo.update_one({'user_id':userID},{"$set":{'defend_token':1}},True)
        else:
            self.user_mongo.update_one({'user_id':userID},{"$set":{'defend_token':token['defend_token']+1}},True)
    
    def get_user_token(self, userID:str):
        '''获取用户的防御token, 以token数量确定概率, 被选定为攻击对象后token+1, token越多被命中概率越高, 被命中一次清零'''
        token=self.user_mongo.find_one({'user_id':userID,'defend_token':{'$gt':0}}) # 大于0的豁免token记录
        if not token:
            return 0
        return token['defend_token']
    
    
    def process_raw_data(self, raw_txt):
        reslut = ''

        additionTable = [
            # '~w♡',
            '...',
            '~♡...',
            '...嗯...!',
            '...哈啊♡...',
            '~!...'
            '♡嗯啊！...',
        ]
        max_gap = 1
        is_in_cqmsg = 0
        temp = ''
        for t in raw_txt:
            if t == '[':
                is_in_cqmsg=1
            if (not is_in_cqmsg and random.random() > 0.2) or t == ' ':
                temp = t
                reslut += t
                continue
            addChar = random.choice(additionTable)+temp
            gap = 0
            while addChar != '' and gap < max_gap and not is_in_cqmsg:
                gap += 1
                reslut += addChar
                addChar = random.choice(additionTable)
                
            if t == ']':
                is_in_cqmsg = 0

            reslut += t
            temp = t

        return reslut


gagControlPanel = gagController()
