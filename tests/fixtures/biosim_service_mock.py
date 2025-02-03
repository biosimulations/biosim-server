import logging
import uuid

from typing_extensions import override

from biosim_server.common.biosim1_client import BiosimService, Hdf5DataValues, HDF5File
from biosim_server.common.database.data_models import BiosimulatorVersion, BiosimSimulationRun, \
    BiosimSimulationRunStatus

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class ObjectNotFoundError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)


class BiosimServiceMock(BiosimService):
    sim_runs: dict[str, BiosimSimulationRun] = {}
    hdf5_files: dict[str, HDF5File] = {}
    hdf5_data: dict[str, dict[str, Hdf5DataValues]] = {}

    def __init__(self,
                 sim_runs: dict[str, BiosimSimulationRun] | None = None,
                 hdf5_files: dict[str, HDF5File] | None = None,
                 hdf5_data: dict[str, dict[str, Hdf5DataValues]] | None = None) -> None:
        if sim_runs:
            self.sim_runs = sim_runs
        if hdf5_files:
            self.hdf5_files = hdf5_files
        if hdf5_data:
            self.hdf5_data = hdf5_data

    @override
    async def get_sim_run(self, simulation_run_id: str) -> BiosimSimulationRun:
        logger.info(f"Polling MOCK simulation with simulation run_id {simulation_run_id}")
        sim_run = self.sim_runs[simulation_run_id]
        if sim_run:
            return sim_run
        else:
            raise ObjectNotFoundError("Simulation run not found")

    @override
    async def run_biosim_sim(self, local_omex_path: str, omex_name: str, simulator_version: BiosimulatorVersion) -> BiosimSimulationRun:
        logger.info(f"Submitting MOCK simulation for {omex_name} with local path {local_omex_path} with simulator {simulator_version.id}")
        sim_id = "mock_"+str(uuid.uuid4().hex)
        sim_run = BiosimSimulationRun(
            id=sim_id,
            name=omex_name,
            simulator_version=simulator_version,
            status=BiosimSimulationRunStatus.RUNNING
        )
        self.sim_runs[sim_id] = sim_run
        return sim_run

    @override
    async def get_hdf5_metadata(self, simulation_run_id: str) -> HDF5File:
        hdf5_file = self.hdf5_files[simulation_run_id]
        if hdf5_file:
            return hdf5_file
        else:
            raise ObjectNotFoundError("HDF5 metadata not found")

    @override
    async def get_hdf5_data(self, simulation_run_id: str, dataset_name: str) -> Hdf5DataValues:
        all_hdf5_values: dict[str, Hdf5DataValues] = self.hdf5_data[simulation_run_id]
        if all_hdf5_values:
            return all_hdf5_values[dataset_name]
        else:
            raise ObjectNotFoundError("HDF5 metadata not found")

    @override
    async def get_simulator_versions(self) -> list[BiosimulatorVersion]:
        sim_versions_ndjson: str = \
        """
        {"id":"ginsim","name":"GINsim","version":"3.0.0b","image_url":"ghcr.io/biosimulators/ginsim:3.0.0b","image_digest":"sha256:7b884d0a7d44a157d0e1a4e066ec15b70f8550c664e73c626f79760a82b9b538","created":"2021-01-07T05:25:30.823Z","updated":"2021-12-22T19:13:13.825Z"}
        {"id":"boolnet","name":"BoolNet","version":"2.1.5","image_url":"ghcr.io/biosimulators/boolnet:2.1.5","image_digest":"sha256:4a9c10d923b25d4d2e7c729a18d2c3a19ab56203e76a3f9bc935e24c4f197929","created":"2021-05-04T01:40:37.625Z","updated":"2021-12-22T19:13:14.982Z"}
        {"id":"cbmpy","name":"CBMPy","version":"0.7.25","image_url":"ghcr.io/biosimulators/cbmpy:0.7.25","image_digest":"sha256:95cf691064e447052c4277a950aa7584afa4f9888e9ce77e68b485449889f307","created":"2021-05-04T01:40:20.168Z","updated":"2022-02-23T09:27:41.611Z"}
        {"id":"libsbmlsim","name":"LibSBMLSim","version":"1.4.0","image_url":"ghcr.io/biosimulators/libsbmlsim:1.4.0","image_digest":"sha256:c5cbaf7d68b10d252bf433909606f84dfd6da9bb139d889bb9cbc0a759c6033f","created":"2021-01-07T05:32:46.514Z","updated":"2021-12-22T19:13:21.680Z"}
        {"id":"rbapy","name":"RBApy","version":"1.0.2","image_url":"ghcr.io/biosimulators/rbapy:1.0.2","image_digest":"sha256:ba864d2add5b444da6fbbc274b4eb633963e9c677b686c602efb6610b10d1ec3","created":"2021-05-16T19:31:12.490Z","updated":"2021-12-22T19:13:25.720Z"}
        {"id":"netpyne","name":"NetPyNe","version":"1.0.0.2","image_url":"ghcr.io/biosimulators/netpyne:1.0.0.2","image_digest":"sha256:7b379580e509151589a34fc398f77c9bb2e33b7c460e9ac74db98798328f0547","created":"2021-06-03T04:55:08.854Z","updated":"2022-02-23T00:30:50.302Z"}
        {"id":"neuron","name":"NEURON","version":"8.0.0","image_url":"ghcr.io/biosimulators/neuron:8.0.0","image_digest":"sha256:423142e072688a52b0d7d58073b91dc4d9f6fd4cd7b75d9259c10ef89c276f7c","created":"2021-06-03T04:55:44.841Z","updated":"2021-12-16T20:37:22.458Z"}
        {"id":"xpp","name":"XPP","version":"8.0","image_url":"ghcr.io/biosimulators/xpp:8.0","image_digest":"sha256:b8e41eb7175de41d3bfcf1ff5679389e12af4350a4cdcbc56caa4ed52f3b64f0","created":"2021-08-09T12:09:39.325Z","updated":"2022-02-28T21:41:32.225Z"}
        {"id":"smoldyn","name":"Smoldyn","version":"2.67","image_url":"ghcr.io/biosimulators/smoldyn:2.67","image_digest":"sha256:763d25a0dac503231a541ed18e7fabd19728b4c3d11d9d378297d5f776477c08","created":"2021-08-12T15:07:33.550Z","updated":"2021-11-02T20:03:34.707Z"}
        {"id":"copasi","name":"COPASI","version":"4.34.251","image_url":"ghcr.io/biosimulators/copasi:4.34.251","image_digest":"sha256:d3331edfa2f0d8c51a28e57543ecc59d537bf5a7d557652c455cf57a6d23a08b","created":"2021-08-15T00:23:05.813Z","updated":"2021-12-22T19:13:28.331Z"}
        {"id":"cobrapy","name":"COBRApy","version":"0.22.1","image_url":"ghcr.io/biosimulators/cobrapy:0.22.1","image_digest":"sha256:55fb3d94a2abeb72cef904abe8dc71fc82744962081916e15536812ad2baba62","created":"2021-08-18T05:13:18.740Z","updated":"2022-02-23T09:29:59.347Z"}
        {"id":"pysces","name":"PySceS","version":"1.0.0","image_url":"ghcr.io/biosimulators/pysces:1.0.0","image_digest":"sha256:cb9bf5ce922c6a9595d9d0f632eba66c343fd3477e9119eccbaf47b50a4b64bf","created":"2021-09-20T19:30:46.062Z","updated":"2021-12-22T19:13:30.831Z"}
        {"id":"bionetgen","name":"BioNetGen","version":"2.7.0","image_url":"ghcr.io/biosimulators/bionetgen:2.7.0","image_digest":"sha256:db5314da674b51f02f0339c3bf90b85d91d530182f6b92a7ca6bd6527ce6425c","created":"2021-09-30T18:53:39.962Z","updated":"2021-12-22T19:13:32.452Z"}
        {"id":"opencor","name":"OpenCOR","version":"2021-10-05","image_url":"ghcr.io/biosimulators/opencor:2021-10-05","image_digest":"sha256:9a575dca3a0d2c0fba4b1d299484d272a5c496353811423030c6082cda8e7036","created":"2021-10-05T07:20:31.116Z","updated":"2022-01-03T18:10:40.474Z"}
        {"id":"tellurium","name":"tellurium","version":"2.2.1","image_url":"ghcr.io/biosimulators/tellurium:2.2.1","image_digest":"sha256:2464aa62d911f99e7cfae07de73ac21eb6bc94fdaf5a65813c465616e2c72a01","created":"2021-10-15T13:57:40.484Z","updated":"2021-12-22T19:13:33.690Z"}
        {"id":"vcell","name":"Virtual Cell","version":"7.4.0.26","image_url":"ghcr.io/biosimulators/vcell:7.4.0.26","image_digest":"sha256:9777aa903ee1cde473fcdf2121679d5f4425a90b175db45385c35171dbeeda6f","created":"2021-10-28T05:58:52.751Z","updated":"2022-01-18T23:25:58.009Z"}
        {"id":"pyneuroml","name":"pyNeuroML","version":"0.5.18","image_url":"ghcr.io/biosimulators/pyneuroml:0.5.18","image_digest":"sha256:c9b3ffd354ee53feb908e1bc41c2305a741d74bfd2fb75b115da59f469d406d8","created":"2021-12-16T20:37:49.397Z","updated":"2021-12-16T20:37:49.397Z"}
        {"id":"brian2","name":"Brian 2","version":"2.5.0.1","image_url":"ghcr.io/biosimulators/brian2:2.5.0.1","image_digest":"sha256:7886dbb7d524c2fbe5bde4dc8b8613af50b3aa29283d57cf5a20ea6b256c8380","created":"2021-12-16T21:05:07.896Z","updated":"2021-12-16T21:05:07.896Z"}
        {"id":"gillespy2","name":"GillesPy2","version":"1.6.6","image_url":"ghcr.io/biosimulators/gillespy2:1.6.6","image_digest":"sha256:e024021c3ac4f7ad70793ceb487c98b80da17356a286a22610c092a2d8973199","created":"2021-12-22T16:17:41.914Z","updated":"2022-02-25T22:19:38.607Z"}
        {"id":"amici","name":"AMICI","version":"0.11.22","image_url":"ghcr.io/biosimulators/amici:0.11.22","image_digest":"sha256:5f18fee43188b0b4afe17373492e2b7862901fd6f22304f0b052d494ff83fb1c","created":"2021-12-22T16:49:11.450Z","updated":"2021-12-22T16:49:11.450Z"}
        {"id":"masspy","name":"MASSpy","version":"0.1.5","image_url":"ghcr.io/biosimulators/masspy:0.1.5","image_digest":"sha256:707acbb88a1874204846f3090988f114232b082796ae9c81e2633f4da4cfb2df","created":"2021-12-22T16:51:46.842Z","updated":"2021-12-22T16:51:46.842Z"}
        {"id":"smoldyn","name":"Smoldyn","version":"2.67.1","image_url":"ghcr.io/biosimulators/smoldyn:2.67.1","image_digest":"sha256:aa38507d6aff9ceb7d227b5dbd7b07c87839d2cb9f97fce66afc4589530a66d2","created":"2022-01-11T09:03:11.794Z","updated":"2022-01-11T09:03:11.794Z"}
        {"id":"amici","name":"AMICI","version":"0.11.23","image_url":"ghcr.io/biosimulators/amici:0.11.23","image_digest":"sha256:7ab1bf4960bf8e22097d2269a86ad33d98a6229498382ab6628ea25095fe2c5e","created":"2022-01-11T16:56:03.608Z","updated":"2022-01-11T16:56:03.608Z"}
        {"id":"smoldyn","name":"Smoldyn","version":"2.67.2","image_url":"ghcr.io/biosimulators/smoldyn:2.67.2","image_digest":"sha256:abc34e2573d90ec5424b141a0a5f3814ac2619c5c0e69a1168b58bda8cace366","created":"2022-01-12T05:32:30.992Z","updated":"2022-01-12T05:32:30.992Z"}
        {"id":"vcell","name":"Virtual Cell","version":"7.4.0.33","image_url":"ghcr.io/biosimulators/vcell:7.4.0.33","image_digest":"sha256:60681afa6b8ed5728d0a450e04f770ce7d93ecf78548e262f60984fa924c8630","created":"2022-01-25T17:20:22.630Z","updated":"2022-01-25T17:20:22.630Z"}
        {"id":"vcell","name":"Virtual Cell","version":"7.4.0.34","image_url":"ghcr.io/biosimulators/vcell:7.4.0.34","image_digest":"sha256:7a3c3c5a735f6f432801b384f4cf345f1bbf1f2a739ece11e46864b9783ad9a3","created":"2022-01-25T20:20:18.702Z","updated":"2022-01-25T20:20:18.702Z"}
        {"id":"amici","name":"AMICI","version":"0.11.24","image_url":"ghcr.io/biosimulators/amici:0.11.24","image_digest":"sha256:92b2116a6e2f5fcd08bcde61d0a8e83710b27a5880978e63abb3ef17e9cbff6d","created":"2022-02-01T20:21:08.860Z","updated":"2022-02-01T20:21:08.860Z"}
        {"id":"amici","name":"AMICI","version":"0.11.25","image_url":"ghcr.io/biosimulators/amici:0.11.25","image_digest":"sha256:8d25d3ead8f8c134ffc3d306b447bc05821ecf0ecd1fc2cf57e6c09831772fe0","created":"2022-02-09T15:58:25.528Z","updated":"2022-02-23T01:07:28.451Z"}
        {"id":"vcell","name":"Virtual Cell","version":"7.4.0.37","image_url":"ghcr.io/biosimulators/vcell:7.4.0.37","image_digest":"sha256:814fb1ef97f448280b5db024eeaa594c97bce7e4d2ab5982cb075ee630813e5f","created":"2022-02-19T06:37:32.051Z","updated":"2022-02-23T00:37:26.138Z"}
        {"id":"neuron","name":"NEURON","version":"8.0.2","image_url":"ghcr.io/biosimulators/neuron:8.0.2","image_digest":"sha256:0b7f8ddd450d0cb22e915704247eb20bb24889ec6120f0d6b0ec3f1a6e6193e0","created":"2022-02-22T22:39:39.081Z","updated":"2022-02-23T00:26:56.216Z"}
        {"id":"pyneuroml","name":"pyNeuroML","version":"0.5.20","image_url":"ghcr.io/biosimulators/pyneuroml:0.5.20","image_digest":"sha256:0592ac601916a4cddb9398823a539e209224c5919cca214a275296aa7a46d6b3","created":"2022-02-22T22:40:18.690Z","updated":"2022-02-23T00:31:26.241Z"}
        {"id":"brian2","name":"Brian 2","version":"2.5.0.3","image_url":"ghcr.io/biosimulators/brian2:2.5.0.3","image_digest":"sha256:1587b4dd3b5505ab25a965f8a81d902984854bbef13c6f1b8cf631af35b45cff","created":"2022-02-22T23:10:49.003Z","updated":"2022-02-23T00:52:59.894Z"}
        {"id":"cobrapy","name":"COBRApy","version":"0.23.0","image_url":"ghcr.io/biosimulators/cobrapy:0.23.0","image_digest":"sha256:477fa2018f3817b00432394b1bb291dcfdbde4d13f8cb69a68094bc2c4c2ab92","created":"2022-02-23T09:33:42.829Z","updated":"2022-02-23T09:33:42.829Z"}
        {"id":"cobrapy","name":"COBRApy","version":"0.24.0","image_url":"ghcr.io/biosimulators/cobrapy:0.24.0","image_digest":"sha256:9c4e5c5b429897a3af56b78e69ac1e28542428823d41750279cda5fe28a3080b","created":"2022-02-23T09:33:50.798Z","updated":"2022-02-23T09:33:50.798Z"}
        {"id":"masspy","name":"MASSpy","version":"0.1.6","image_url":"ghcr.io/biosimulators/masspy:0.1.6","image_digest":"sha256:eb21d48b8033e0de75c4674458b476d72ff3f82c7f1066d63417608fd430e100","created":"2022-02-23T17:01:33.305Z","updated":"2022-02-23T17:01:33.305Z"}
        {"id":"vcell","name":"Virtual Cell","version":"7.4.0.38","image_url":"ghcr.io/biosimulators/vcell:7.4.0.38","image_digest":"sha256:e8dd40d48cdaf1b11208a7c3e669eca37fb031d5225b5b4d96eb267ae730dcfe","created":"2022-02-26T20:28:22.174Z","updated":"2022-03-01T22:03:49.369Z"}
        {"id":"bionetgen","name":"BioNetGen","version":"2.8.0","image_url":"ghcr.io/biosimulators/bionetgen:2.8.0","image_digest":"sha256:6b64ba14726b7f28921db5b96c8331c6bd9d0e2e541d4fe83fba2366a5593edb","created":"2022-02-27T23:26:30.297Z","updated":"2022-02-27T23:26:30.297Z"}
        {"id":"smoldyn","name":"Smoldyn","version":"2.67.3","image_url":"ghcr.io/biosimulators/smoldyn:2.67.3","image_digest":"sha256:5d4939cf99097ebbe972eef327ee86a43e2dc20a629e756347c660fd3e71f0b6","created":"2022-03-17T06:59:48.176Z","updated":"2022-03-17T06:59:48.176Z"}
        {"id":"copasi","name":"COPASI","version":"4.35.258","image_url":"ghcr.io/biosimulators/copasi:4.35.258","image_digest":"sha256:f4aeff7c2057e26840231f1969a1eda8ee2ba93e7470989b1d295d4e45158311","created":"2022-03-26T20:13:49.341Z","updated":"2022-03-26T20:13:49.341Z"}
        {"id":"copasi","name":"COPASI","version":"4.36.260","image_url":"ghcr.io/biosimulators/copasi:4.36.260","image_digest":"sha256:00e1b6c5414d3f4d7c2646c6da11ddf2cb402905217f7181e0be487a3fe62222","created":"2022-05-07T00:33:41.325Z","updated":"2022-05-07T03:42:59.968Z"}
        {"id":"vcell","name":"Virtual Cell","version":"7.4.0.48","image_url":"ghcr.io/biosimulators/vcell:7.4.0.48","image_digest":"sha256:03f0e622174dfaf313a40e45be7c839aecfca252b4ddefc66dff49838b2ec23e","created":"2022-06-02T23:50:31.780Z","updated":"2022-06-03T16:09:24.038Z"}
        {"id":"vcell","name":"Virtual Cell","version":"7.4.0.68","image_url":"ghcr.io/biosimulators/vcell:7.4.0.68","image_digest":"sha256:190a1eed6736057a167ff60ea3698731b157626176b7a9e9e5784c9d032c35d7","created":"2022-10-09T02:09:27.657Z","updated":"2022-11-17T20:40:13.195Z"}
        {"id":"smoldyn","name":"Smoldyn","version":"2.69","image_url":"ghcr.io/biosimulators/smoldyn:2.69","image_digest":"sha256:992788cd8b5c6f7d6cf3a5c6a39f4f3b9426075074b76306004ac997cb15fe75","created":"2022-10-17T22:14:58.637Z","updated":"2022-10-17T22:14:58.637Z"}
        {"id":"smoldyn","name":"Smoldyn","version":"2.70","image_url":"ghcr.io/biosimulators/smoldyn:2.70","image_digest":"sha256:af970afed751bcd79401d9640a81e381fb16cd8cac8388daec0719b6130862c0","created":"2022-10-25T20:24:40.464Z","updated":"2022-10-25T20:24:40.464Z"}
        {"id":"tellurium","name":"tellurium","version":"2.2.8","image_url":"ghcr.io/biosimulators/tellurium:2.2.8","image_digest":"sha256:8142fc0f07418f77a27785f1797f4c74e72ca6554b613360d3c62236e728d931","created":"2023-04-26T22:58:31.193Z","updated":"2023-08-22T20:33:35.997Z"}
        {"id":"vcell","name":"Virtual Cell","version":"7.5.0.28","image_url":"ghcr.io/biosimulators/vcell:7.5.0.28","image_digest":"sha256:18e6ac855aa6b5bfe70cc245b10300e815ddcefefb4f57cdd149d7be5b15ec71","created":"2023-04-27T18:36:07.696Z","updated":"2023-04-27T18:36:10.207Z"}
        {"id":"vcell","name":"Virtual Cell","version":"7.5.0.30","image_url":"ghcr.io/biosimulators/vcell:7.5.0.30","image_digest":"sha256:10caecb4952a830c8306700dd0d9b7c21a99f51010edc47624ad722811c86741","created":"2023-05-19T16:40:11.480Z","updated":"2023-05-19T18:22:44.969Z"}
        {"id":"vcell","name":"Virtual Cell","version":"7.5.0.34","image_url":"ghcr.io/biosimulators/vcell:7.5.0.34","image_digest":"sha256:576883cf2685297400b7f976985f03dc8d1fbf8b46525a2fbef8e41e10b6021e","created":"2023-05-31T17:32:27.689Z","updated":"2023-05-31T17:32:27.689Z"}
        {"id":"vcell","name":"Virtual Cell","version":"7.5.0.36","image_url":"ghcr.io/biosimulators/vcell:7.5.0.36","image_digest":"sha256:096446479e4ae135b9147104b540a9a6d6223279c98661c42f43081ac5fba21d","created":"2023-06-11T11:11:35.216Z","updated":"2023-06-11T11:11:38.520Z"}
        {"id":"vcell","name":"Virtual Cell","version":"7.5.0.37","image_url":"ghcr.io/biosimulators/vcell:7.5.0.37","image_digest":"sha256:47979e5c16f910fcc0cc08f6ef57d109d89245573d31ef4b41ad52bb924bb72c","created":"2023-06-14T01:14:58.495Z","updated":"2023-06-14T01:15:01.865Z"}
        {"id":"amici","name":"AMICI","version":"0.18.1","image_url":"ghcr.io/biosimulators/amici:0.18.1","image_digest":"sha256:cf17b7a576bdb9ef0134590e7da3e757d11765086b8f51ea3ee84cd088fa171d","created":"2023-06-26T19:34:53.827Z","updated":"2023-06-28T23:37:07.198Z"}
        {"id":"vcell","name":"Virtual Cell","version":"7.5.0.45","image_url":"ghcr.io/biosimulators/vcell:7.5.0.45","image_digest":"sha256:78ae012e68a32c2d0cb9548079eb5e62b88ab74f0b349cb5fab7580712f7a9e6","created":"2023-06-27T23:59:53.889Z","updated":"2023-06-28T02:07:05.438Z"}
        {"id":"smoldyn","name":"Smoldyn","version":"2.72","image_url":"ghcr.io/ssandrews/smoldyn/biosimulators_smoldyn:2.72","image_digest":"sha256:8aa0cd3eb3b0219dda000f243b4745dc3965fe5f1c082a2dfb611b7ae77edbc6","created":"2023-08-17T22:22:54.405Z","updated":"2024-02-17T17:15:37.296Z"}
        {"id":"copasi","name":"COPASI","version":"4.41.280","image_url":"ghcr.io/biosimulators/copasi:4.41.280","image_digest":"sha256:af7951180e324ca7e35060be8e55ac70712c5e7d0036df10a5802d7d1fad5347","created":"2023-08-25T19:07:38.220Z","updated":"2023-08-25T19:07:38.220Z"}
        {"id":"vcell","name":"Virtual Cell","version":"7.5.0.80","image_url":"ghcr.io/biosimulators/vcell:7.5.0.80","image_digest":"sha256:0554056282005ed410a5e3e2ed86c72c2ead8bcd571210964bf2a6c14645c199","created":"2023-11-28T13:29:11.878Z","updated":"2023-11-28T13:29:11.878Z"}
        {"id":"vcell","name":"Virtual Cell","version":"7.5.0.86-dev1","image_url":"ghcr.io/biosimulators/vcell:7.5.0.86-dev1","image_digest":"sha256:fab48bdd2c620acaf334f8e60ab87858f2816ea87b6160d48f510a43dc152a43","created":"2024-01-31T19:22:15.576Z","updated":"2024-01-31T19:22:15.576Z"}
        {"id":"vcell","name":"Virtual Cell","version":"7.5.0.89","image_url":"ghcr.io/biosimulators/vcell:7.5.0.89","image_digest":"sha256:9c47976b6358c6083d33269c5fd8ea67f2cd507333177b9d4b7f49843dae56eb","created":"2024-02-02T13:34:17.908Z","updated":"2024-02-02T13:34:17.908Z"}
        {"id":"vcell","name":"Virtual Cell","version":"7.5.0.99","image_url":"ghcr.io/biosimulators/vcell:7.5.0.99","image_digest":"sha256:84c1cf7409ef07ea53a220e85cff6b182694b6f781d8f3502a908486d406b97e","created":"2024-02-14T20:39:58.191Z","updated":"2024-02-14T20:39:58.191Z"}
        {"id":"vcell","name":"Virtual Cell","version":"7.5.0.108","image_url":"ghcr.io/biosimulators/vcell:7.5.0.108","image_digest":"sha256:2ebcd968564459002769e567cd451f5c41e76add179bae27a9a43497e138ff00","created":"2024-03-08T20:55:06.865Z","updated":"2024-03-08T20:55:06.865Z"}
        {"id":"copasi","name":"COPASI","version":"4.42.284","image_url":"ghcr.io/biosimulators/copasi:4.42.284","image_digest":"sha256:915c10cdfe3066ff754f2a67727b73b825c5195ae6258e578a8f41556685d909","created":"2024-03-14T23:16:17.377Z","updated":"2024-03-14T23:16:17.377Z"}
        {"id":"vcell","name":"Virtual Cell","version":"7.5.0.121","image_url":"ghcr.io/biosimulators/vcell:7.5.0.121","image_digest":"sha256:1a369286e15a6146f249acc029027991e0619cc18c8e452d0fc96f2e534604ca","created":"2024-04-09T17:57:20.066Z","updated":"2024-04-09T17:57:20.066Z"}
        {"id":"vcell","name":"Virtual Cell","version":"7.5.0.127","image_url":"ghcr.io/biosimulators/vcell:7.5.0.127","image_digest":"sha256:0089380af4a4a54f7c30b5ca25dc81aa3e3130f41bb137de236cf35cbca32538","created":"2024-04-16T14:35:02.465Z","updated":"2024-04-16T14:35:02.465Z"}
        {"id":"pysces","name":"PySCeS","version":"1.2.1","image_url":"ghcr.io/biosimulators/pysces:1.2.1","image_digest":"sha256:a9f364bd9e00c0bbfae9fa3c8adb6a63a593a5cc4d980df225399c5eb8bbe7e1","created":"2024-05-10T09:19:11.947Z","updated":"2024-05-10T09:19:11.947Z"}
        {"id":"vcell","name":"Virtual Cell","version":"7.6.0.40","image_url":"ghcr.io/biosimulators/vcell:7.6.0.40","image_digest":"sha256:530a2009fdd549ef1e23c0475358d8b245b3fe45ad4d07f0be89d13536cd6397","created":"2024-09-17T15:33:19.867Z","updated":"2024-09-17T15:33:19.867Z"}
        {"id":"pysces","name":"PySCeS","version":"1.2.2","image_url":"ghcr.io/biosimulators/pysces:1.2.2","image_digest":"sha256:0bba7f884629bf1b2ab6cb81ccd4d57a1512c09c196fe3cc4bb6a15f7edaf37f","created":"2024-09-20T05:19:47.046Z","updated":"2024-10-18T23:49:11.213Z"}
        {"id":"copasi","name":"COPASI","version":"4.44.295","image_url":"ghcr.io/biosimulators/copasi:4.44.295","image_digest":"sha256:6a0b2b782e983ad9de38767696c769d43e411d96d1070289c66838eecbfbfdfd","created":"2024-09-22T17:44:11.157Z","updated":"2024-10-07T14:17:00.652Z"}
        {"id":"tellurium","name":"tellurium","version":"2.2.10","image_url":"ghcr.io/biosimulators/tellurium:2.2.10","image_digest":"sha256:0c22827b4682273810d48ea606ef50c7163e5f5289740951c00c64c669409eae","created":"2024-10-10T22:00:50.110Z","updated":"2024-10-10T22:00:50.110Z"}
        {"id":"masspy","name":"MASSpy","version":"0.1.7","image_url":"ghcr.io/biosimulators/masspy:0.1.7","image_digest":"sha256:13a7ce784cf0561150d1e0623c47de84496068f59444589123d9ea845b7aaeae","created":"2024-10-30T04:42:36.591Z","updated":"2024-10-31T04:29:42.164Z"}
        {"id":"vcell","name":"Virtual Cell","version":"7.7.0.7","image_url":"ghcr.io/biosimulators/vcell:7.7.0.7","image_digest":"sha256:50d06ccff8be3c5496a29ee3a3ce9b168d81955ceacce1808b4a3ae7b3ddb1c5","created":"2024-11-15T22:49:41.255Z","updated":"2024-11-15T22:49:41.255Z"}
        {"id":"copasi","name":"COPASI","version":"4.45.296","image_url":"ghcr.io/biosimulators/copasi:4.45.296","image_digest":"sha256:7c9cd076eeec494a653353777e42561a2ec9be1bfcc647d0ea84d89fe18999df","created":"2024-11-18T15:34:26.233Z","updated":"2024-11-18T15:34:26.233Z"}
        {"id":"vcell","name":"Virtual Cell","version":"7.7.0.9","image_url":"ghcr.io/biosimulators/vcell:7.7.0.9","image_digest":"sha256:cfe9c9110a4d69ffc713afc2d51cb81c6f31a44950304fd8818a5678d67d2791","created":"2024-11-21T23:17:38.159Z","updated":"2024-11-21T23:17:38.159Z"}
        {"id":"vcell","name":"Virtual Cell","version":"7.7.0.10","image_url":"ghcr.io/biosimulators/vcell:7.7.0.10","image_digest":"sha256:02494e4d849cf0681ee546b029e8f548694ca0cef1bb70127a69bf951183cb3a","created":"2024-11-27T22:38:05.409Z","updated":"2024-11-27T22:38:05.409Z"}
        {"id":"vcell","name":"Virtual Cell","version":"7.7.0.12","image_url":"ghcr.io/biosimulators/vcell:7.7.0.12","image_digest":"sha256:6ab82cfc60518c5810d61dd47ad1e9acbfd539cb7d0f177e9e122997a30c6035","created":"2024-12-10T20:53:06.192Z","updated":"2024-12-10T20:53:06.192Z"}
        {"id":"vcell","name":"Virtual Cell","version":"7.7.0.13","image_url":"ghcr.io/biosimulators/vcell:7.7.0.13","image_digest":"sha256:828b2dc2b983de901c2d68eeb415cb22b46f1db04cdb9e8815d80bf451005216","created":"2024-12-13T16:56:12.395Z","updated":"2024-12-13T16:56:12.395Z"}
        """
        sim_versions = []
        for line in sim_versions_ndjson.strip().split("\n"):
            sim_versions.append(BiosimulatorVersion.model_validate_json(line.strip()))
        return sim_versions

    @override
    async def close(self) -> None:
        pass
