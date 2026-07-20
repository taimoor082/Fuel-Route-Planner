from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from routes.serializers import RouteRequestSerializer
from routes.services.geocoding import GeocodingError
from routes.services.planner import PlanningError, plan_trip
from routes.services.routing import RoutingError


class RoutePlanView(APIView):
    def get(self, request):
        serializer = RouteRequestSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        try:
            result = plan_trip(
                serializer.validated_data['start'],
                serializer.validated_data['finish'],
            )
        except (GeocodingError, PlanningError) as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except RoutingError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        return Response(result)
