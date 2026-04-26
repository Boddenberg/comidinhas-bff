from __future__ import annotations

from fastapi import APIRouter, Depends, File, Path, Query, UploadFile

from app.api.dependencies import get_manage_place_photos_use_case, get_manage_places_use_case
from app.api.v1.routes.profiles import get_access_token
from app.modules.places.photo_use_cases import ManagePlacePhotosUseCase
from app.modules.places.schemas import (
    PlaceCreateRequest,
    PlaceListParams,
    PlaceListResponse,
    PlacePhotoResponse,
    PlaceResponse,
    PlaceSortBy,
    PlaceSortOrder,
    PlaceStatus,
    PlaceUpdateRequest,
    ReorderPhotosRequest,
)
from app.modules.places.use_cases import ManagePlacesUseCase

router = APIRouter(prefix="/places", tags=["places"])


@router.get(
    "/",
    response_model=PlaceListResponse,
    summary="Lista lugares com paginacao, busca e filtros",
)
async def list_places(
    group_id: str | None = Query(default=None, description="UUID do grupo. Se omitido, usa o grupo ativo do usuario."),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None, max_length=120, description="Busca por nome, categoria ou bairro"),
    category: str | None = Query(default=None, max_length=80),
    neighborhood: str | None = Query(default=None, max_length=80),
    status: PlaceStatus | None = Query(default=None),
    is_favorite: bool | None = Query(default=None),
    price_range: int | None = Query(default=None, ge=1, le=4),
    price_range_min: int | None = Query(default=None, ge=1, le=4),
    price_range_max: int | None = Query(default=None, ge=1, le=4),
    sort_by: PlaceSortBy = Query(default=PlaceSortBy.CREATED_AT),
    sort_order: PlaceSortOrder = Query(default=PlaceSortOrder.DESC),
    access_token: str = Depends(get_access_token),
    use_case: ManagePlacesUseCase = Depends(get_manage_places_use_case),
) -> PlaceListResponse:
    params = PlaceListParams(
        group_id=group_id,
        page=page,
        page_size=page_size,
        search=search,
        category=category,
        neighborhood=neighborhood,
        status=status,
        is_favorite=is_favorite,
        price_range=price_range,
        price_range_min=price_range_min,
        price_range_max=price_range_max,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return await use_case.list_places(access_token=access_token, params=params)


@router.post(
    "/",
    response_model=PlaceResponse,
    status_code=201,
    summary="Adiciona um novo lugar ao grupo",
)
async def create_place(
    request: PlaceCreateRequest,
    access_token: str = Depends(get_access_token),
    use_case: ManagePlacesUseCase = Depends(get_manage_places_use_case),
) -> PlaceResponse:
    return await use_case.create_place(access_token=access_token, request=request)


@router.get(
    "/{place_id}",
    response_model=PlaceResponse,
    summary="Retorna o detalhe de um lugar",
)
async def get_place(
    place_id: str = Path(..., min_length=8, max_length=64),
    access_token: str = Depends(get_access_token),
    use_case: ManagePlacesUseCase = Depends(get_manage_places_use_case),
) -> PlaceResponse:
    return await use_case.get_place(access_token=access_token, place_id=place_id)


@router.patch(
    "/{place_id}",
    response_model=PlaceResponse,
    summary="Atualiza campos de um lugar",
)
async def update_place(
    request: PlaceUpdateRequest,
    place_id: str = Path(..., min_length=8, max_length=64),
    access_token: str = Depends(get_access_token),
    use_case: ManagePlacesUseCase = Depends(get_manage_places_use_case),
) -> PlaceResponse:
    return await use_case.update_place(
        access_token=access_token,
        place_id=place_id,
        request=request,
    )


@router.delete(
    "/{place_id}",
    summary="Remove um lugar",
)
async def delete_place(
    place_id: str = Path(..., min_length=8, max_length=64),
    access_token: str = Depends(get_access_token),
    use_case: ManagePlacesUseCase = Depends(get_manage_places_use_case),
) -> dict:
    return await use_case.delete_place(access_token=access_token, place_id=place_id)


# ---------------------------------------------------------------- place photos


@router.get(
    "/{place_id}/photos",
    response_model=list[PlacePhotoResponse],
    summary="Lista todas as fotos de um lugar (ordenadas por sort_order)",
)
async def list_place_photos(
    place_id: str = Path(..., min_length=8, max_length=64),
    access_token: str = Depends(get_access_token),
    use_case: ManagePlacePhotosUseCase = Depends(get_manage_place_photos_use_case),
) -> list[PlacePhotoResponse]:
    return await use_case.list_photos(access_token=access_token, place_id=place_id)


@router.post(
    "/{place_id}/photos",
    response_model=PlacePhotoResponse,
    status_code=201,
    summary="Envia uma nova foto para o lugar (primeira foto vira capa automaticamente)",
)
async def upload_place_photo(
    file: UploadFile = File(...),
    place_id: str = Path(..., min_length=8, max_length=64),
    set_as_cover: bool = Query(default=False, description="Define esta foto como capa"),
    access_token: str = Depends(get_access_token),
    use_case: ManagePlacePhotosUseCase = Depends(get_manage_place_photos_use_case),
) -> PlacePhotoResponse:
    return await use_case.upload_photo(
        access_token=access_token,
        place_id=place_id,
        file=file,
        set_as_cover=set_as_cover,
    )


@router.patch(
    "/{place_id}/photos/{photo_id}/cover",
    response_model=PlacePhotoResponse,
    summary="Define esta foto como a capa do lugar (e remove a capa anterior)",
)
async def set_cover_photo(
    place_id: str = Path(..., min_length=8, max_length=64),
    photo_id: str = Path(..., min_length=8, max_length=64),
    access_token: str = Depends(get_access_token),
    use_case: ManagePlacePhotosUseCase = Depends(get_manage_place_photos_use_case),
) -> PlacePhotoResponse:
    return await use_case.set_cover(
        access_token=access_token,
        place_id=place_id,
        photo_id=photo_id,
    )


@router.patch(
    "/{place_id}/photos/reorder",
    response_model=list[PlacePhotoResponse],
    summary="Reordena as fotos enviando a lista de IDs na nova ordem desejada",
)
async def reorder_photos(
    request: ReorderPhotosRequest,
    place_id: str = Path(..., min_length=8, max_length=64),
    access_token: str = Depends(get_access_token),
    use_case: ManagePlacePhotosUseCase = Depends(get_manage_place_photos_use_case),
) -> list[PlacePhotoResponse]:
    return await use_case.reorder_photos(
        access_token=access_token,
        place_id=place_id,
        request=request,
    )


@router.delete(
    "/{place_id}/photos/{photo_id}",
    summary="Remove uma foto do lugar (se era a capa, a proxima foto assume a capa)",
)
async def delete_place_photo(
    place_id: str = Path(..., min_length=8, max_length=64),
    photo_id: str = Path(..., min_length=8, max_length=64),
    access_token: str = Depends(get_access_token),
    use_case: ManagePlacePhotosUseCase = Depends(get_manage_place_photos_use_case),
) -> dict:
    return await use_case.delete_photo(
        access_token=access_token,
        place_id=place_id,
        photo_id=photo_id,
    )
