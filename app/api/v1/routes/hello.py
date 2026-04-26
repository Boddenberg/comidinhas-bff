from fastapi import APIRouter

router = APIRouter()


@router.get("/hello-world", summary="Endpoint inicial para validar o scaffold")
def hello_world() -> dict[str, str]:
    return {"message": "Hello, world from Comidinhas BFF!"}

