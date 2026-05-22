"""Wrapper fino sobre a REST API do ClickUp."""
import os
import time
import requests

BASE = "https://api.clickup.com/api/v2"


class ClickUp:
    def __init__(self, token: str | None = None):
        self.token = token or os.getenv("CLICKUP_TOKEN")
        if not self.token:
            raise RuntimeError("CLICKUP_TOKEN não configurado no .env")
        self.headers = {"Authorization": self.token, "Content-Type": "application/json"}

    def _req(self, method: str, path: str, **kw):
        url = f"{BASE}{path}"
        r = requests.request(method, url, headers=self.headers, timeout=30, **kw)
        if not r.ok:
            raise RuntimeError(f"{method} {path} -> {r.status_code}: {r.text}")
        return r.json() if r.content else {}

    def get_list(self, list_id: str):
        return self._req("GET", f"/list/{list_id}")

    def get_list_custom_fields(self, list_id: str):
        return self._req("GET", f"/list/{list_id}/field").get("fields", [])

    def get_list_tasks(self, list_id: str, include_closed: bool = True):
        tasks, page = [], 0
        while True:
            data = self._req(
                "GET",
                f"/list/{list_id}/task",
                params={
                    "include_closed": str(include_closed).lower(),
                    "page": page,
                    "subtasks": "false",
                },
            )
            batch = data.get("tasks", [])
            tasks.extend(batch)
            if data.get("last_page", True) or not batch:
                break
            page += 1
            time.sleep(0.2)
        return tasks

    def get_task(self, task_id: str):
        return self._req("GET", f"/task/{task_id}")

    def get_members(self, team_id: str):
        teams = self._req("GET", "/team").get("teams", [])
        for team in teams:
            if str(team.get("id")) == str(team_id):
                return team.get("members", [])
        return []

    def update_task(self, task_id: str, fields: dict):
        return self._req("PUT", f"/task/{task_id}", json=fields)

    def set_custom_field(self, task_id: str, field_id: str, value):
        return self._req("POST", f"/task/{task_id}/field/{field_id}", json={"value": value})

    def create_task(self, list_id: str, name: str, **fields):
        payload = {"name": name, **fields}
        return self._req("POST", f"/list/{list_id}/task", json=payload)

    def delete_task(self, task_id: str):
        return self._req("DELETE", f"/task/{task_id}")

    def add_tag(self, task_id: str, tag: str):
        return self._req("POST", f"/task/{task_id}/tag/{tag}")

    def remove_tag(self, task_id: str, tag: str):
        return self._req("DELETE", f"/task/{task_id}/tag/{tag}")

    def add_comment(self, task_id: str, text: str, notify_all: bool = False):
        return self._req(
            "POST",
            f"/task/{task_id}/comment",
            json={"comment_text": text, "notify_all": notify_all},
        )

    def add_assignee(self, task_id: str, user_id: int):
        return self._req("POST", f"/task/{task_id}/assignee", json={"assignee": user_id})
