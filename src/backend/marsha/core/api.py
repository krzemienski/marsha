"""Declare API endpoints with Django RestFramework viewsets."""
import hashlib
import hmac

from django.apps import apps
from django.conf import settings
from django.utils import timezone

from rest_framework import mixins, viewsets
from rest_framework.decorators import action, api_view
from rest_framework.response import Response

from .defaults import SUBTITLE_SOURCE_MAX_SIZE, VIDEO_SOURCE_MAX_SIZE
from .models import SubtitleTrack, Video
from .permissions import IsRelatedVideoTokenOrAdminUser, IsVideoTokenOrAdminUser
from .serializers import SubtitleTrackSerializer, UpdateStateSerializer, VideoSerializer
from .utils.s3_utils import get_s3_upload_policy_signature
from .utils.time_utils import to_timestamp


@api_view(["POST"])
def update_state(request):
    """View handling AWS POST request to update the state of an object by key.

    Parameters
    ----------
    request : Type[django.http.request.HttpRequest]
        The request on the API endpoint, it should contain a payload with the following fields:
            - key: the key of an object in the source bucket as delivered in the upload policy,
            - state: state of the upload, should be either "ready" or "error",
            - signature: has of the payload salted with a shared secret to authenticate AWS.

    Returns
    -------
    Type[rest_framework.response.Response]
        HttpResponse acknowledging the success or failure of the state update operation.

    """
    serializer = UpdateStateSerializer(data=request.data)

    if serializer.is_valid() is not True:
        return Response(serializer.errors, status=400)

    # The signed message is the s3 object key
    msg = serializer.validated_data["key"]

    # Check if the provided signature is valid against any secret in our list
    #
    # We need to do this to support 2 or more versions of our infrastructure at the same time.
    # It then enables us to do updates and change the secret without incurring downtime.
    signature_is_valid = any(
        serializer.validated_data["signature"]
        == hmac.new(
            secret.encode("utf-8"), msg=msg.encode("utf-8"), digestmod=hashlib.sha256
        ).hexdigest()
        for secret in settings.UPDATE_STATE_SHARED_SECRETS
    )

    if not signature_is_valid:
        return Response("Forbidden", status=403)

    # Retrieve the elements from the key
    key_elements = serializer.get_key_elements()

    # Update the object targeted by the "object_id" and "resource_id"
    model = apps.get_model(app_label="core", model_name=key_elements["model_name"])

    updated = model.objects.filter(id=key_elements["object_id"]).update(
        uploaded_on=key_elements["uploaded_on"],
        state=serializer.validated_data["state"],
    )

    if updated:
        return Response({"success": True})

    return Response({"success": False}, status=404)


class VideoViewSet(
    mixins.RetrieveModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet
):
    """Viewset for the API of the video object."""

    queryset = Video.objects.all()
    serializer_class = VideoSerializer
    permission_classes = [IsVideoTokenOrAdminUser]

    @action(methods=["get"], detail=True, url_path="upload-policy")
    # pylint: disable=unused-argument
    def upload_policy(self, request, pk=None):
        """Get a policy for direct upload of a video to our AWS S3 source bucket.

        Parameters
        ----------
        request : Type[django.http.request.HttpRequest]
            The request on the API endpoint
        pk: string
            The primary key of the video

        Returns
        -------
        Type[rest_framework.response.Response]
            HttpResponse carrying the policy as a JSON object.

        """
        now = timezone.now()
        stamp = to_timestamp(now)

        video = self.get_object()
        key = video.get_source_s3_key(stamp=stamp)

        policy = get_s3_upload_policy_signature(
            now,
            [
                {"key": key},
                ["starts-with", "$Content-Type", "video/"],
                ["content-length-range", 0, VIDEO_SOURCE_MAX_SIZE],
            ],
        )

        policy.update(
            {"key": key, "max_file_size": VIDEO_SOURCE_MAX_SIZE, "stamp": stamp}
        )

        return Response(policy)


class SubtitleTrackViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Viewset for the API of the subtitle object."""

    queryset = SubtitleTrack.objects.all()
    serializer_class = SubtitleTrackSerializer
    permission_classes = [IsRelatedVideoTokenOrAdminUser]

    @action(methods=["get"], detail=True, url_path="upload-policy")
    # pylint: disable=unused-argument
    def upload_policy(self, request, pk=None):
        """Get a policy for direct upload of a subtitle track to our AWS S3 source bucket.

        Parameters
        ----------
        request : Type[django.http.request.HttpRequest]
            The request on the API endpoint
        pk: string
            The primary key of the subtitle track

        Returns
        -------
        Type[rest_framework.response.Response]
            HttpResponse carrying the policy as a JSON object.

        """
        now = timezone.now()
        stamp = to_timestamp(now)

        subtitle_track = self.get_object()
        key = subtitle_track.get_source_s3_key(stamp=stamp)

        policy = get_s3_upload_policy_signature(
            now, [{"key": key}, ["content-length-range", 0, SUBTITLE_SOURCE_MAX_SIZE]]
        )

        policy.update(
            {"key": key, "max_file_size": SUBTITLE_SOURCE_MAX_SIZE, "stamp": stamp}
        )

        return Response(policy)