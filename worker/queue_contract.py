"""Provider-neutral message exchanged between queue and render worker."""


def enqueue_message(render_job_id):
    if not isinstance(render_job_id, str) or not render_job_id.strip():
        raise ValueError("render_job_id must be a non-empty string")
    return {"renderJobId": render_job_id}


def parse_message(message):
    if not isinstance(message, dict) or not isinstance(message.get("renderJobId"), str) or not message["renderJobId"].strip():
        raise ValueError("queue message must contain a non-empty renderJobId")
    return message["renderJobId"]
