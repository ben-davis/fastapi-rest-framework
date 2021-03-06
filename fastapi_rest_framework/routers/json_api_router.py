from typing import Generic, List, Literal, Optional, TypeVar, Union

from fastapi import Query, Request, Response
from pydantic.generics import GenericModel
from pydantic.main import BaseModel

from fastapi_rest_framework.resources.base_resource import Relationships, Resource
from fastapi_rest_framework.resources.types import Inclusions
from fastapi_rest_framework.routers import base_router

from .base_router import ResourceRouter

TRead = TypeVar("TRead", bound=BaseModel)
TName = TypeVar("TName", bound=str)
TIncluded = TypeVar("TIncluded")


class TIncludeParam(str):
    pass


class JAResource(GenericModel, Generic[TRead, TName]):
    id: str
    type: TName
    attributes: TRead


class JAResponseSingle(GenericModel, Generic[TRead, TName, TIncluded]):
    data: JAResource[TRead, TName]
    included: TIncluded


class JAResponseList(GenericModel, Generic[TRead, TName, TIncluded]):
    data: List[JAResource[TRead, TName]]
    included: TIncluded


include_query = Query(None, regex=r"^([\w\.]+)(,[\w\.]+)*$")


def get_schemas_from_relationships(
    relationships: Relationships, visited: set[type[BaseModel]] = None
):
    schemas = []
    visited = visited or set()
    for relationship_info in relationships.values():
        schema = relationship_info.schema_with_relationships.schema
        if schema in visited:
            continue

        visited.add(schema)
        schemas.append(schema)
        schemas += get_schemas_from_relationships(
            relationships=relationship_info.schema_with_relationships.relationships,
            visited=visited,
        )

    return schemas


class JSONAPIResourceRouter(ResourceRouter):
    def __init__(
        self,
        *,
        resource_class: type[Resource],
        **kwargs,
    ) -> None:
        self.resource_class = resource_class

        super().__init__(resource_class=resource_class, **kwargs)

    def get_included_schema(self) -> tuple[type[BaseModel], ...]:
        relationships = self.resource_class.get_relationships()
        schemas = get_schemas_from_relationships(relationships=relationships)

        return tuple(
            JAResource[
                schema,
                Literal[(self.resource_class.registry[schema].name,)],
            ]
            for schema in schemas
        )

    def get_read_response_model(self):
        included_schemas = self.get_included_schema()
        Included = List[Union[included_schemas]] if included_schemas else list
        Read = self.resource_class.Read
        Name = Literal[(self.resource_class.name,)]

        return JAResponseSingle[Read, Name, Included]

    def get_list_response_model(self):
        included_schemas = self.get_included_schema()
        Included = List[Union[included_schemas]] if included_schemas else list
        Read = self.resource_class.Read
        Name = Literal[(self.resource_class.name,)]

        return JAResponseList[Read, Name, Included]

    def get_resource(self, request: Request):
        inclusions: Inclusions = []
        include = request.query_params.get("include")

        if include:
            inclusions = [inclusion.split(".") for inclusion in include.split(",")]

        return self.resource_class(inclusions=inclusions)

    def build_response(
        self,
        rows: Union[BaseModel, list[BaseModel]],
        resource: Resource,
    ):
        included_resources = {}

        many = isinstance(rows, list)
        rows = rows if isinstance(rows, list) else [rows]

        for row in rows:
            for inclusion in resource.inclusions:
                selected_objs = resource.get_related(obj=row, inclusion=inclusion)

                for selected_obj in selected_objs:
                    obj = selected_obj.obj
                    related_resource = selected_obj.resource

                    included_resources[(related_resource.name, obj.id)] = JAResource(
                        id=obj.id,
                        type=related_resource.name,
                        attributes=related_resource.Read.from_orm(obj),
                    )

        data = [
            JAResource(id=row.id, attributes=row, type=resource.name) for row in rows
        ]
        data = data if many else data[0]
        ResponseSchema = JAResponseList if many else JAResponseSingle

        return ResponseSchema(
            data=data,
            included=list(included_resources.values()),
        )

    def _retrieve(
        self,
        *,
        id: Union[int, str],
        request: Request,
        include: Optional[str] = include_query,
    ):
        return super()._retrieve(id=id, request=request)

    def _list(self, *, request: Request, include: Optional[str] = include_query):
        return super()._list(request=request)

    def _create(
        self,
        *,
        create: base_router.TCreatePayload,
        request: Request,
        include: Optional[str] = include_query,
    ):
        return super()._create(create=create, request=request)

    def _update(
        self,
        *,
        id: Union[int, str],
        update: base_router.TUpdatePayload,
        request: Request,
        include: Optional[str] = include_query,
    ):
        return super()._update(id=id, update=update, request=request)

    def _delete(self, *, id: Union[int, str], request: Request):
        return super()._delete(id=id, request=request)
