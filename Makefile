.PHONY: install test lint run up down
install:
	pip install -r requirements-dev.txt
test:
	pytest
lint:
	ruff check .
run:
	uvicorn app.main:app --reload
up:
	docker compose up --build
down:
	docker compose down
