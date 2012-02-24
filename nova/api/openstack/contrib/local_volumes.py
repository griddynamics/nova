import logging
import os
from nova.api.openstack import common
from nova import exception
from nova.api.openstack.extensions import ExtensionDescriptor
from nova.api.openstack import extensions, faults
from webob import exc
import webob
import re
from nova.localvolume.api import LocalAPI
from nova.volume import volume_types

LOG = logging.getLogger("nova.api.local_volumes")

def _translate_volume_detail_view(vol):
    """Maps keys for volumes details view."""

    d = _translate_volume_summary_view(vol)

    # No additional data / lookups at the moment

    return d

def _translate_volume_summary_view(vol):
    """Maps keys for volumes summary view."""
    d = {'id': vol['id'],
        'status': vol['status'],
        'size': vol['size'],
        'instance_id': vol['instance_id'],
        'device': vol['device'],
        'createdAt': vol['created_at']}

    return d

class LocalVolumeController(object):
    """Disk controller for OS API"""
    def __init__(self):
        self.local_volume_api = LocalAPI()

    def create(self, req, body):
        context = req.environ['nova.context']

        vol = body['volume']

        vol_type = vol.get('volume_type', None)
        if vol_type:
            try:
                vol_type = volume_types.get_volume_type_by_name(context,
                    vol_type)
            except exception.NotFound:
                return faults.Fault(exc.HTTPNotFound())

        metadata = vol.get('metadata', None)

        new_volume = self.local_volume_api.create_local(context,
            instance_id=vol['instance_id'],
            snapshot_id=vol.get('snapshot_id'),
            device=vol['device'],
            size=self._get_size(vol.get('size')),
            description=vol.get('display_description'),
            volume_type=vol_type,
            metadata=metadata)

        new_volume = self.local_volume_api.get(context, new_volume['id'])

        retval = _translate_volume_detail_view(new_volume)

        return {'volume': retval}

    def delete(self, req, id):
        """Delete a volume."""
        volume_id = id
        context = req.environ['nova.context']

        LOG.audit(_("Delete volume with id: %s"), volume_id, context=context)

        try:
            self.local_volume_api.delete(context, volume_id)
        except exception.NotFound:
            return faults.Fault(exc.HTTPNotFound())
        return webob.Response(status_int=202)

    def index(self, req):
        """Returns a summary list of volumes."""
        return self._items(req, entity_maker=_translate_volume_summary_view)

    def _items(self, req, entity_maker):
        """Returns a list of volumes, transformed through entity_maker."""
        context = req.environ['nova.context']

        volumes = self.local_volume_api.get_all(context)
        limited_list = common.limited(volumes, req)
        res = [entity_maker(vol) for vol in limited_list]
        return {'volumes': res}

    def _get_size(self, parameter):
        if not parameter:
            return parameter

        modifiers = {
            '':  1,
            'b': 1,
            'K': 1024,
            'M': 1024 * 1024,
            'G': 1024 * 1024 * 1024
        }
        match = re.search('^(?P<size>[0-9]+)(?P<modifier>[A-Za-z]?)$', parameter)
        if not match:
            raise RuntimeError('Invalid parameter: %s' % parameter)
        size = int(match.group('size'))
        modifier = match.group('modifier')
        if modifier not in modifiers:
            raise RuntimeError('Only %s modifiers supported' % modifiers.keys())

        return size * modifiers[modifier]

    def update(self, req, id, body):
        context = req.environ.get('nova.context')
        vol = body['volume']
        volume_id = id
        new_size = self._get_size(vol['size'])
        LOG.audit(_("Resizing volume with id: %s to size %s"), volume_id, vol['size'])
        try:
            self.local_volume_api.resize(context, volume_id, new_size)
        except exception.NotFound:
            return faults.Fault(exc.HTTPNotFound())
        return webob.Response(status_int=202)


class LocalVolumeSnapshottingController(object):
    """Local volume controller for OS API"""
    def __init__(self):
        self.local_volume_api = LocalAPI()

    def create(self, req, body):
        context = req.environ['nova.context']
        try:
            volume_id = body["volume_id"]
            image_name = body["name"]
            force_snapshot = body.get("force_snapshot", False)

        except KeyError:
            msg = _("Creating snapshot requires snapshot name, volume_id attributes")
            raise webob.exc.HTTPBadRequest(explanation=msg)

        except TypeError:
            msg = _("Malformed body data")
            raise webob.exc.HTTPBadRequest(explanation=msg)

        try:
            self.local_volume_api.snapshot(context,
                volume_id,
                image_name,
                force_snapshot)
        except exception.InstanceBusy:
            msg = _("Server is currently creating an image. Please wait.")
            raise webob.exc.HTTPConflict(explanation=msg)

        resp = webob.Response(status_int=202)
        return resp




class Local_volumes(ExtensionDescriptor):

    def get_updated(self):
        return "2012-01-25T00:00:00+00:00"

    def get_resources(self):
        resources = []

        res = extensions.ResourceExtension('gd-local-volumes', LocalVolumeController())
        resources.append(res)

        res = extensions.ResourceExtension('gd-local-volumes-snapshotting', LocalVolumeSnapshottingController())
        resources.append(res)

        return resources

    def get_description(self):
        return "Local Volumes support"

    def get_alias(self):
        return "gd-local-volumes"

    def get_name(self):
        return "Local_volumes"

    def get_namespace(self):
        return "http://docs.openstack.org/ext/local-volumes/api/v1.1"