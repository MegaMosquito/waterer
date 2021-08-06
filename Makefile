
DOCKERHUB_ID:=ibmosquito
NAME:=waterer
VERSION:=1.0.0
PORT:=8080

# Some bits from https://github.com/MegaMosquito/netstuff/blob/master/Makefile
LOCAL_DEFAULT_ROUTE     := $(shell sh -c "ip route | grep default")
LOCAL_ROUTER_ADDRESS    := $(word 3, $(LOCAL_DEFAULT_ROUTE))
LOCAL_IP_ADDRESS        := $(word 7, $(LOCAL_DEFAULT_ROUTE))

all: build run

build:
	docker build -t $(DOCKERHUB_ID)/$(NAME):$(VERSION) .

dev: build stop
	-docker rm -f $(NAME) 2> /dev/null || :
	touch ./config.json ./log.json
	docker run -it --privileged \
            --name $(NAME) \
	    -e LOCAL_IP_ADDRESS=$(LOCAL_IP_ADDRESS) \
	    -p $(PORT):$(PORT) \
	    -v /etc/localtime:/etc/localtime \
	    -v `pwd`/config.json:/config.json \
	    -v `pwd`/log.json:/log.json \
	    -v `pwd`:/outside \
	    $(DOCKERHUB_ID)/$(NAME):$(VERSION) /bin/sh

run: stop
	-docker rm -f $(NAME) 2>/dev/null || :
	touch ./config.json ./log.json
	docker run -d --privileged \
            --name $(NAME) --restart unless-stopped \
	    -e LOCAL_IP_ADDRESS=$(LOCAL_IP_ADDRESS) \
	    -p $(PORT):$(PORT) \
	    -v /etc/localtime:/etc/localtime \
	    -v `pwd`/config.json:/config.json \
	    -v `pwd`/log.json:/log.json \
	    $(DOCKERHUB_ID)/$(NAME):$(VERSION)

exec:
	docker exec -it $(NAME) /bin/sh

push:
	docker push $(DOCKERHUB_ID)/$(NAME):$(VERSION)

test:
	curl -sS localhost:8080/status | jq .

stop:
	-docker rm -f $(NAME) 2>/dev/null || :

clean: stop
	-docker rmi $(DOCKERHUB_ID)/$(NAME):$(VERSION) 2>/dev/null || :

.PHONY: all build dev run exec stop test clean

