class SystemService:
    @staticmethod
    def open_application(app_id: str):
        """
        Controlled entrypoint for opening an application.
        Returns a structured action to the frontend.
        """
        return {"action": "app.open", "target": app_id}

    @staticmethod
    def close_application(app_id: str):
        """
        Controlled entrypoint for closing an application.
        Returns a structured action to the frontend.
        """
        return {"action": "app.close", "target": app_id}

