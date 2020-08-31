import time
import logging
import traceback
import configparser
from threading import Thread
import requests
from requests.exceptions import ConnectionError

config = configparser.ConfigParser()
config.read('config.ini')

# константы
# slack
token = config['slack']['token']
headers = {'Content-type': 'application/json'}
postheaders = {'Content-type': 'application/json', 'Authorization': 'Bearer '+token}

# CONVERSATION_ID, который надо слушать
# например https://app.slack.com/client/TSLV5AS03/CTECTHJLD
# CTECTHJLD - conversation_id
listenids = config['slack']['listenids']

listenids = listenids.split(',')
n = 0
for listenid in listenids:
    listenids[n] = listenid.strip()
    n += 1

# teamwork
apikey = config['teamwork']['apikey']
domain = config['teamwork']['domain']
tasklistid = config['teamwork']['tasklistid']

# логгирование
errors = logging.getLogger("errors")
log = logging.getLogger("main")

# ConnectionError
delay = int(config['disconnect']['delay'])
showmessage = eval(config['disconnect']['showmessage'])

log_level = int(config['general']['log_level'])

errors.setLevel(log_level)
log.setLevel(log_level)

FH = logging.FileHandler("log.txt", encoding='utf8')
ERRORS_FH = logging.FileHandler("errors.txt", encoding='utf8')
log.addHandler(FH)
errors.addHandler(ERRORS_FH)

FORMATTER = logging.Formatter('%(name)s [%(asctime)s] - %(message)s')
FH.setFormatter(FORMATTER)
ERRORS_FH.setFormatter(FORMATTER)

def readts():
    try:
        with open('ts.txt', 'r') as f:
            ts = f.read()
            return ts
    except FileNotFoundError:
        errors.warning('не найден ts.txt')
        return 0

def writets(ts):
    with open('ts.txt', 'w+') as f:
        f.write(ts)
        return ts

def post_message(j):
    requests.post('https://slack.com/api/chat.postMessage', json=j, headers=postheaders)

def createtask(title, description, userid, listenid):
    log.debug('инициализация создания задачи')

    email = requests.get('https://slack.com/api/users.info',
                         {'token': token, 'user': userid}).json()['user']['profile']['email']

    log.debug(f'получен email отправителя сообщения {email=}')

    projectid = requests.get(domain+'/tasklists/'+tasklistid+'.json',
                             auth=(apikey, ''),
                             headers=headers).json()['todo-list']['projectId']

    team = requests.get(domain+'/projects/'+projectid+'/people.json',
                        auth=(apikey, ''),
                        headers=headers).json()
    id = None

    for people in team['people']:
        if people['user-name'] == email and people['permissions']['add-tasks'] == '1':
            id = people['id']
            break

    if id is None:
        log.warning(f'сообщение отправил неизвестный человек, либо человек без права на создание задач, отказ в доступе')
        requests.post('https://slack.com/api/chat.postMessage',
                      json={'channel': listenid, 'text': 'Невозможно создать задачу, нет прав.'},
                      headers=postheaders)

        return 'permissionerror'

    item = {'content': title, 'description': description, 'commentFollowerIds': id, 'changeFollowerIds': id}
    r = requests.post(domain+'/tasklists/'+tasklistid+'/tasks.json', json={'todo-item':item}, auth=(apikey, ''), headers=headers)

    log.debug(f'получен ответ о создании задачи {r.status_code=}\n{r.text}')

    r = r.json()

    if r['STATUS'] == 'OK':
        log.info('задача создана УСПЕШНО')
        j = {'channel': listenid, 'text': 'status: {}\n{}/#/tasks/{}'.format(r['STATUS'], domain, r['id'])}
    else:
        log.info('при создании задачи произошла ошибка')
        j = {'channel': listenid, 'text': 'status: {}\n{}'.format(r['STATUS'], r['MESSAGE'])}

    Thread(target=post_message, args=(j,)).start()

ts = readts()
tasks = {}

log.info("Начинаю опрашивать сервер на предмет новых сообщений")
print('ver2 начинаю опрашивать сервер на предмет новых сообщений')
while True:
    try:
        for listenid in listenids:
            r = requests.get('https://slack.com/api/conversations.history?token={}&oldest={}&channel={}'.format(token, ts, listenid)).json()
            # print(f'{r=}')

            if 'messages' in r:
                messages = r['messages']
            else:
                errors.error(r)
                raise Exception('Ошибка запроса к slack api')

            if messages != []:
                ts = writets(messages[0]['ts'])
                for message in messages:
                    if 'user' in message:
                        uid = message['user']
                        if not uid in tasks:
                            tasks[uid] = {}
                            tasks[uid]['step'] = 0

                        if 'начать' in message['text'].lower() and tasks[uid]['step'] == 0:
                            log.debug('получена команда "начать"')
                            j = {'channel': listenid, 'text': 'Укажите Наименование задачи – номер проекта для которого вам требуется квота и название компонента/группы компонентов на которые вы хотите получить квоту.'}
                            Thread(target=post_message, args=(j,)).start()
                            tasks[uid]['step'] = 1

                        elif tasks[uid]['step'] == 1:
                            j = {'channel': listenid, 'text': 'Введите описание задачи: размер партии закупки, part numbers компонентов (или их тех. описания для подбора компонентов), другие требования. На английском языке.'}
                            tasks[uid]['title'] = message['text']
                            Thread(target=post_message, args=(j,)).start()
                            tasks[uid]['step'] = 2

                        elif tasks[uid]['step'] == 2:
                            tasks[uid]['description'] = message['text']
                            Thread(target=createtask,
                                   args=(tasks[uid]['title'], tasks[uid]['description'],
                                         message['user'], listenid)).start()

                            tasks[uid]['step'] = 0

        time.sleep(1.5)
    except (ConnectionError, ConnectionResetError) as e:
        if showmessage is True:
            print(f'Ошибка соединения, попытка переподключится через {delay} c')

        errors.warning(f'Ошибка соединения, попытка переподключится через {delay} c')
        errors.warning(str(e))

        time.sleep(delay)
        continue

    except Exception as e:
        print('При выполнении кода произошла ошибка - %s' % str(e))
        traceback.print_exc()
        errors.exception('При выполнении кода произошла ошибка - %s' % str(e))
        break

log.info('Завершение работы')
print('Завершение работы')
