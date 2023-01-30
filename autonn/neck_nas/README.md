README
---

# autonn/neck_nas

**Quick Start**
```bash
docker rm -f $(docker ps -aq)
docker rmi autonn_nk:lastest
cd {tango_root}/autonn/neck_nas
docker build -t autonn_nk .
docker run -it --gpus=all --ipc=host -p 8089:8089 --name=autonn_nk autonn_nk:lastest
python manage.py makemigrations
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver 0.0.0.0:8089
curl -v http://localhost:8089/start?user_id=root\&project_id=20230118
curl -v http://localhost:8089/status_request?user_id=root\&project_id=20230118
curl -v http://localhost:8089/stop?user_id=root\&project_id=20230118
```

## TANGO 신경망 자동 생성 모듈 / 'Neck' Network Architeture Search 컨테이너
#### 도커 서비스 이름
    autonn_nk

### REST APIs
#### GET /start
    parameter : userid, project_id
    return: 200 OK
    return content: "starting" / "error"
    return content-type: text/plain

#### GET /stop
    parameter : userid, project_id
    return: 200 OK
    return content: "finished" / "error"
    return content-type: text/plain

#### GET /status_request
    parameter : userid, project_id
    return: 200 OK
    return content: "ready" / started" / "runnung" / "stopped" / "failed" / "completed"
    return content-type: text/plain

### PORT
    8089

**Note**
> URL for neck architeture search is temporary assigned for simple testing of container behavior.  
Now you can launch web browser and open URL `http://localhost:8089/`  
Run using CURL 'curl -v http://localhost:8089/start?userid=root\&project_id=2023'


---
### PORT 번호 변경시
####  docker-compose.yaml 파일 수정
    'autonn_nk' 항목의 'command' 명령어 수정 ( 기존 8089 PORT 번호 변경 )
    'autonn_nk' 항목의 'ports' 수정         ( 기존 8089 PORT 번호 변경 )

#### Project Manager 소스코드 수정 필요

---
### Docker volume
    ./autonn/neck_nas --> /source
    ./shared          --> shared

---
### DB
    ~/autonn/neck_nas/backend/setting.py 파일 수정
    Django 기본 DB인 sqlite3 사용 (./db.sqlite3/)

---
# Super-Neck

What is the best neck for your data and/or device? 
We've researched many different neck architecure for object detection and thought about 
how we could compare them fairly, the most importantly, search and find out the best architecture.
 
Super-Neck Architecture
![superneck1](./documents/images/super_neck_1.png)

