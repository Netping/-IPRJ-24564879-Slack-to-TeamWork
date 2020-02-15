import logging
import requests
import time
import configparser

config = configparser.ConfigParser()
config.read('config.ini')

#константы
#slack
token = config['slack']['token']
headers = {'Content-type': 'application/json'}
postheaders = {'Content-type': 'application/json', 'Authorization': 'Bearer '+token}

#CONVERSATION_ID, который надо слушать 
#например https://app.slack.com/client/TSLV5AS03/CTECTHJLD
#CTECTHJLD - conversation_id
listenid = config['slack']['listenid']

#teamwork
apikey = config['teamwork']['apikey']
domain = config['teamwork']['domain']
tasklistid = config['teamwork']['tasklistid']

logging.basicConfig(filename="log.log", level=logging.INFO)

def readts():
    try:    
        with open('ts.txt', 'r') as f:
            ts = f.read()
            return ts
    except FileNotFoundError:
        logging.warning('не найден ts.txt')
        return 0

def writets(ts):
    with open('ts.txt', 'w+') as f:
        f.write(ts)
        return ts
        
def createtask(title, description, userid):
    logging.info('инициализация создания задачи')
    email = requests.get('https://slack.com/api/users.info',{'token': token,'user': userid}).json()['user']['profile']['email']
    logging.info(f'получен email отправителя сообщения {email=}')
    projectid = requests.get(domain+'/tasklists/'+tasklistid+'.json', auth=(apikey, ''), headers=headers).json()['todo-list']['projectId']
    team = requests.get(domain+'/projects/'+projectid+'/people.json', auth=(apikey, ''), headers=headers).json()
    logging.info('получен список сотрудников')
    id = None
    for people in team['people']:
        if people['email-address'] == email and people['permissions']['add-tasks'] == '1':
            id = people['id']
            logging.info(f'сообщение отправил человек с {id=}')
            break
    if id is None:
        logging.warning(f'сообщение отправил неизвестный человек, либо человек без права на создание задач, отказ в доступе')
        requests.post('https://slack.com/api/chat.postMessage',json={'channel': listenid, 'text': 'Невозможно создать задачу, нет прав.'},headers=postheaders)
        return 'permissionerror'
    item = {'content': title, 'description': description, 'commentFollowerIds': id, 'changeFollowerIds': id}
    r = requests.post(domain+'/tasklists/'+tasklistid+'/tasks.json',json={'todo-item':item}, auth=(apikey, ''), headers=headers)
    logging.info(f'получен ответ о создании задачи {r.status_code=}\n{r.text}')
    return r.json()

ts = readts()
logging.info("ts прочитан")
task = {'step': 0}

logging.info("начинаю опрашивать сервер на предмет новых сообщений")
while True:
    r = requests.get('https://slack.com/api/conversations.history?token={}&channel={}&oldest={}'.format(token,listenid,ts)).json()
    print(f'{r=}')
    messages = r['messages']

    if messages != []:
        logging.info("получены новые сообщения")
        ts = writets(messages[0]['ts'])
        logging.info("ts обновлён")
        for message in messages:
            if not 'bot_id' in message:
                if 'начать' in message['text'].lower() and task['step'] == 0:
                    logging.info('получена команда "начать"')
                    j = {'channel': listenid, 'text': 'Укажите Наименование задачи – номер проекта для которого вам требуется квота и название компонента/группы компонентов на которые вы хотите получить квоту.'}
                    requests.post('https://slack.com/api/chat.postMessage',json=j,headers=postheaders)
                    logging.info('отправлен ответ')
                    task['step'] = 1
                    logging.info('присвоен 1-й шаг')
                elif task['step'] == 1:
                    j = {'channel': listenid, 'text': 'Введите описание задачи: размер партии закупки, part numbers компонентов (или их тех. описания для подбора компонентов), другие требования. На английском языке.'}
                    task['title'] = message['text']
                    logging.info('получено название задачи')
                    requests.post('https://slack.com/api/chat.postMessage',json=j,headers=postheaders)
                    logging.info('отправлен ответ')
                    task['step'] = 2
                    logging.info('присвоен 2-й шаг')
                elif task['step'] == 2:
                    task['description'] = message['text']
                    logging.info('получено описание задачи')
                    t = createtask(task['title'],task['description'],message['user'])
                    if t == 'permissionerror':
                        task['step'] = 0
                        logging.info('присвоен 0-й шаг')
                        continue
                    elif t['STATUS'] == 'OK':
                        logging.info('задача создана УСПЕШНО')
                        j = {'channel': listenid, 'text': 'status: {}\n{}/#/tasks/{}'.format(t['STATUS'],domain,t['id'])}
                    else:
                        logging.info('при создании задачи произошла ошибка')
                        j = {'channel': listenid, 'text': 'status: {}\n{}'.format(t['STATUS'],t['MESSAGE'])}
                    requests.post('https://slack.com/api/chat.postMessage',json=j,headers=postheaders)
                    logging.info('отправлен ответ')
                    task['step'] = 0
                    logging.info('присвоен 0-й шаг')

    time.sleep(0.65)

while True: input()